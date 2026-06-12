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

## Deploy on Railway

This repo is ready for Railway's Python builder. Railway detects the Python app
from `requirements.txt`, installs packages such as `SQLAlchemy`, and uses
`railway.json` for the production start command and health check.

1. Push this repository to GitHub.
2. In Railway, create a new project from the GitHub repo.
3. Add a PostgreSQL database service to the same Railway project.
4. In the app service variables, add:

```text
QUACK_ENV=production
QUACK_SECRET_KEY=<long random secret>
QUACK_SESSION_COOKIE_SECURE=true
QUACK_SEED_INITIAL_USERS=true
QUACK_ADMIN_USERNAME=MainAdmin
QUACK_ADMIN_EMAIL=<your admin email>
QUACK_ADMIN_PASSWORD=<strong admin password>
```

Railway PostgreSQL provides `DATABASE_URL` automatically. The app reads it
directly, so you do not need to set `QUACK_DATABASE_URI` unless you want to
override the database URL manually.

Keep `QUACK_ADMIN_USERNAME=MainAdmin` if you want the app's built-in owner
protections to apply. After the first successful login, set
`QUACK_SEED_INITIAL_USERS=false` in Railway. The existing admin account will stay
in the database.

5. Generate a public Railway domain for the app service.

If Railway reports `ModuleNotFoundError` for a package listed in
`requirements.txt`, make sure the latest `requirements.txt` and `railway.json`
are pushed to GitHub, then redeploy the app service.

Railway will use this start command from `railway.json`:

```text
gunicorn wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120
```

The health check path is:

```text
/healthz
```

### Local production check

Install production dependencies locally:

```powershell
pip install -r requirements.txt
```

Then run with production-style settings:

```powershell
$env:QUACK_ENV = "production"
$env:QUACK_SECRET_KEY = "local-test-secret"
$env:PORT = "8000"
gunicorn wsgi:application --bind 0.0.0.0:$env:PORT
```

Note: Gunicorn runs on Linux, which is what Railway uses. On Windows, keep using
`python run.py` for local development.
