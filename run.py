"""Startup helper for Quack Wiki.

Run this file with the system Python. It creates a project virtual environment
when needed, installs the runtime dependencies, and starts either the local
Flask development server or a production server for hosting.
"""

import os
import socket
import subprocess
import sys


DEPLOY_MODE = any(arg.lower() in {"deploy", "prod", "production"} for arg in sys.argv[1:])
HOST = os.environ.get("QUACK_HOST") or os.environ.get("HOST") or "0.0.0.0"
PORT = os.environ.get("QUACK_PORT") or os.environ.get("PORT") or "5000"


def get_lan_ip():
    """Best-effort lookup for the LAN address other devices should use."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "localhost"

print("==========================================")
print(" Spustanie Flask aplikacie (automaticky)")
print("==========================================\n")

# Run all commands from the project directory, even when the file is launched elsewhere.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Create the local virtual environment on first run.
venv_path = ".venv"
if not os.path.exists(venv_path):
    print("Vytvaram virtualne prostredie...")
    subprocess.check_call([sys.executable, "-m", "venv", venv_path])

# Choose the virtualenv Python executable for the current platform.
if os.name == "nt":
    python_bin = os.path.join(venv_path, "Scripts", "python.exe")
else:
    python_bin = os.path.join(venv_path, "bin", "python")

print("Aktivujem virtualne prostredie...")

# Make sure pip is present in newly created venvs.
print("Kontrolujem pip...")
subprocess.check_call([python_bin, "-m", "ensurepip", "--upgrade"])
if os.environ.get("QUACK_UPGRADE_PIP") == "1":
    subprocess.check_call([python_bin, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

# Ensure the packages imported by main.py/forms.py/models.py are installed.
required_packages = [
    "flask",
    "email_validator",
    "flask-login",
    "flask-sqlalchemy",
    "flask-wtf",
    "sqlalchemy",
    "werkzeug",
    "wtforms",
]
if DEPLOY_MODE and os.name != "nt":
    required_packages.append("gunicorn")

print("Kontrolujem potrebne balicky...")
for pkg in required_packages:
    try:
        subprocess.check_call([python_bin, "-m", "pip", "show", pkg], stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print(f"Instalujem {pkg}...")
        subprocess.check_call([python_bin, "-m", "pip", "install", pkg])

print("\n==========================================")
if DEPLOY_MODE:
    print("Spustam Flask aplikaciu v deploy rezime...")
    print(f"Server pocuva na: {HOST}:{PORT}")
else:
    print("Spustam Flask aplikaciu...")
    print(f"Na tomto pocitaci otvor: http://127.0.0.1:{PORT}")
    if HOST in {"0.0.0.0", "::"}:
        print(f"Na inom zariadeni v rovnakej sieti otvor: http://{get_lan_ip()}:{PORT}")
    else:
        print(f"Server bude pocuvat iba na hoste: {HOST}")
print("==========================================\n")

env = os.environ.copy()
env["FLASK_APP"] = "main.py"
env["FLASK_DEBUG"] = "0" if DEPLOY_MODE else "1"

if DEPLOY_MODE and os.name != "nt":
    subprocess.check_call([
        python_bin,
        "-m",
        "gunicorn",
        "--bind",
        f"{HOST}:{PORT}",
        "main:app",
    ], env=env)
else:
    subprocess.check_call([
        python_bin,
        "-m",
        "flask",
        "run",
        "--host",
        HOST,
        "--port",
        PORT,
    ], env=env)

print("\n==========================================")
print("Flask server bol ukonceny.")
print("==========================================")
if sys.stdin.isatty() and not DEPLOY_MODE:
    input("Stlac lubovolnu klavesu pre zatvorenie okna...")
