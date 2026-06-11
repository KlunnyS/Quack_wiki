# Quack_wiki

## Run locally

Start the project with:

```powershell
python run.py
```

`run.py` creates `.venv` when it is missing, installs the Flask dependencies,
and starts the development server.

Open the site on this computer at:

```text
http://127.0.0.1:5000
```

The server listens on `0.0.0.0` by default, so another device on the same
network can open the LAN URL printed by `run.py`.

Optional overrides:

```powershell
$env:QUACK_HOST = "127.0.0.1"
$env:QUACK_PORT = "8000"
python run.py
```

## Deploy command

For cloud hosting, use:

```bash
python run.py deploy
```

Deploy mode reads the hosting provider's `PORT` environment variable, disables
Flask debug mode, and uses `gunicorn` on Linux hosts.
