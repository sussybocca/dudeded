from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify
import os
import uuid
import json
import subprocess
import secrets
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAMES_DIR = os.path.join(BASE_DIR, 'games')
LOGS_FILE = os.path.join(BASE_DIR, 'logs')  # per spec, store logins in a file called `logs`
EMAIL_LOG = os.path.join(BASE_DIR, 'emails.log')

os.makedirs(GAMES_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get('CASS_SECRET') or secrets.token_hex(16)


def load_users():
    users = {}
    if not os.path.exists(LOGS_FILE):
        return users
    with open(LOGS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                users[obj['username']] = obj
            except json.JSONDecodeError:
                # skip malformed lines
                continue
    return users


def save_user(user):
    # append-only for simplicity
    with open(LOGS_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(user) + '\n')


def send_email(to_email, subject, body):
    # For the prototype we write emails to a local log and print them.
    with open(EMAIL_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'to': to_email, 'subject': subject, 'body': body}) + '\n')
    print(f"[email to={to_email}] {subject}\n{body}")


@app.route('/')
def index():
    return redirect(url_for('editor'))


@app.route('/editor')
def editor():
    return render_template('editor.html')


@app.route('/submit', methods=['POST'])
def submit_code():
    # accept file upload or raw code
    code = None
    filename = request.form.get('filename') or 'app.py'
    if 'file' in request.files and request.files['file'].filename:
        f = request.files['file']
        filename = secure_filename(f.filename)
        code = f.read().decode('utf-8')
    else:
        code = request.form.get('code')

    if not code:
        return jsonify({'error': 'no code provided'}), 400

    game_id = str(uuid.uuid4())
    game_path = os.path.join(GAMES_DIR, game_id)
    os.makedirs(game_path, exist_ok=True)
    file_path = os.path.join(game_path, filename)
    with open(file_path, 'w', encoding='utf-8') as wf:
        wf.write(code)

    # Run the user script with a timeout of 20 seconds
    try:
        proc = subprocess.run([
            os.environ.get('PYTHON_EXECUTABLE', 'python'),
            file_path
        ], capture_output=True, text=True, timeout=20, check=False)
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        output = 'ERROR: Execution timed out after 20 seconds.'
    except (OSError, subprocess.SubprocessError) as e:
        output = f'ERROR: {e}'

    return jsonify({'game_id': game_id, 'output': output})


@app.route('/games')
def list_games():
    games = []
    for gid in os.listdir(GAMES_DIR):
        gpath = os.path.join(GAMES_DIR, gid)
        if os.path.isdir(gpath):
            files = os.listdir(gpath)
            games.append({'id': gid, 'files': files})
    return render_template('games.html', games=games)


@app.route('/run/<game_id>')
def run_game(game_id):
    gpath = os.path.join(GAMES_DIR, game_id)
    if not os.path.isdir(gpath):
        return 'Game not found', 404
    # find app.py or game.py
    target = None
    for candidate in ('app.py', 'game.py'):
        cpath = os.path.join(gpath, candidate)
        if os.path.exists(cpath):
            target = cpath
            break
    if not target:
        # pick first file
        files = os.listdir(gpath)
        if not files:
            return 'No runnable file', 400
        target = os.path.join(gpath, files[0])

    try:
        proc = subprocess.run([
            os.environ.get('PYTHON_EXECUTABLE', 'python'),
            target
        ], capture_output=True, text=True, timeout=20, check=False)
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        output = 'ERROR: Execution timed out after 20 seconds.'
    except (OSError, subprocess.SubprocessError) as e:
        output = f'ERROR: {e}'

    return render_template('run.html', output=output, game_id=game_id)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    username = request.form.get('username')
    email = request.form.get('email')
    if not username or not email:
        flash('username and email required')
        return redirect(url_for('register'))
    users = load_users()
    if username in users:
        flash('username exists')
        return redirect(url_for('register'))

    verification_code = secrets.token_hex(4)
    user = {
        'username': username,
        'email': email,
        'password_hash': None,
        'verified': False,
        'verification_code': verification_code
    }
    save_user(user)
    send_email(email, 'cass verification code', f'Your code: {verification_code}')
    flash('Verification code sent to email (see emails.log in prototype).')
    return redirect(url_for('verify', username=username))


@app.route('/verify/<username>', methods=['GET', 'POST'])
def verify(username):
    if request.method == 'GET':
        return render_template('verify.html', username=username)
    code = request.form.get('code')
    users = load_users()
    u = users.get(username)
    if not u:
        flash('user not found')
        return redirect(url_for('register'))
    if u.get('verification_code') != code:
        flash('invalid code')
        return redirect(url_for('verify', username=username))

    # mark verified and generate auto password
    auto_password = secrets.token_urlsafe(8)
    u['verified'] = True
    u['verification_code'] = None
    u['password_hash'] = generate_password_hash(auto_password)
    save_user(u)
    send_email(u['email'], 'cass account password', f'Your auto-generated password: {auto_password}')
    flash('Account verified. Password sent to your email (emails.log).')
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    username = request.form.get('username')
    password = request.form.get('password')
    users = load_users()

    # special cass.login behavior: if username endswith '.cass.log' auto-login
    if username and username.endswith('.cass.log'):
        base = username.replace('.cass.log', '')
        u = users.get(base)
        if u:
            session['user'] = base
            flash('Auto-logged in via cass.login')
            return redirect(url_for('editor'))
        else:
            flash('cass.login user not found')
            return redirect(url_for('login'))

    u = users.get(username)
    if not u:
        flash('invalid credentials')
        return redirect(url_for('login'))
    if not u.get('verified'):
        flash('account not verified')
        return redirect(url_for('login'))
    if not check_password_hash(u.get('password_hash', ''), password or ''):
        flash('invalid credentials')
        return redirect(url_for('login'))

    session['user'] = username
    flash('logged in')
    return redirect(url_for('editor'))


@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('logged out')
    return redirect(url_for('login'))


@app.route('/static/games/<game_id>/<path:filename>')
def game_static(game_id, filename):
    return send_from_directory(os.path.join(GAMES_DIR, game_id), filename)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
