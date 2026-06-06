"""Local startup helper for Quack Wiki.

The script creates a project virtual environment when needed, installs the
runtime Flask dependencies, and starts the development server.
"""

import os
import socket
import subprocess
import sys


HOST = "0.0.0.0"
PORT = "5000"


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

# Run all commands from the project directory, even when launched elsewhere.
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

# Uncomment if the bundled pip version needs to be upgraded.
# print("Aktualizujem pip...")
# subprocess.check_call([python_bin, "-m", "pip", "install", "--upgrade", "pip"])

# Ensure the packages imported by main.py/forms.py/models.py are installed.
required_packages = [
    "flask",
    "flask-wtf",
    "flask-sqlalchemy",
    "email_validator",
    "flask-login"
]

print("Kontrolujem potrebne balicky...")
for pkg in required_packages:
    try:
        subprocess.check_call([python_bin, "-m", "pip", "show", pkg], stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print(f"Instalujem {pkg}...")
        subprocess.check_call([python_bin, "-m", "pip", "install", pkg])

# Start Flask in debug mode for local development.
print("\n==========================================")
print("Spustam Flask aplikaciu...")
print(f"Na tomto pocitaci otvor: http://127.0.0.1:{PORT}")
print(f"Na inom zariadeni v rovnakej sieti otvor: http://{get_lan_ip()}:{PORT}")
print("==========================================\n")

env = os.environ.copy()
env["FLASK_APP"] = "main.py"
env["FLASK_ENV"] = "development"

subprocess.check_call([
    python_bin,
    "-m",
    "flask",
    "run",
    "--debug",
    "--host",
    HOST,
    "--port",
    PORT,
], env=env)

print("\n==========================================")
print("Flask server bol ukonceny.")
print("==========================================")
input("Stlac lubovolnu klavesu pre zatvorenie okna...")
