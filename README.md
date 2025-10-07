# cass game prototype

This is a small Flask prototype that implements the requested behavior:
- Monaco editor frontend (with Pyodide for local runs)
- Upload or paste a Python `app.py`/`game.py` and submit to the server
- Server saves the file under `games/` and runs it with a 20s timeout
- Simple file-backed auth in `logs` and email simulation in `emails.log`

Running locally:

1. Create a virtualenv and install dependencies:

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

2. Start the server:

```powershell
python app.py
```

3. Open http://localhost:8080/editor

Notes:
- This is a prototype. Do not expose to the internet without hardening (sandboxing, resource limits, secure email, etc.).
