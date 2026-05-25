import os
import sys
import subprocess
import shutil

print("==========================================")
print(" Spustanie Flask aplikacie (automaticky)")
print("==========================================\n")

# --- Presun do priecinka so suborom ---
# Python skript sa automaticky spustí v aktuálnom priečinku
# Ak chceš byť istejší:
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# --- Vytvor virtualne prostredie, ak neexistuje ---
venv_path = ".venv"
if not os.path.exists(venv_path):
    print("Vytvaram virtualne prostredie...")
    subprocess.check_call([sys.executable, "-m", "venv", venv_path])

# --- Aktivacia v Python subprocess ---
if os.name == "nt":
    python_bin = os.path.join(venv_path, "Scripts", "python.exe")
else:
    python_bin = os.path.join(venv_path, "bin", "python")

print("Aktivujem virtualne prostredie...")

# --- Upgrade pip ---
# print("Aktualizujem pip...")
# subprocess.check_call([python_bin, "-m", "pip", "install", "--upgrade", "pip"])

# --- Kontrola a instalacia balickov ---
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

# --- Spustenie Flask aplikacie ---
print("\n==========================================")
print("Spustam Flask aplikaciu...")
print("==========================================\n")

env = os.environ.copy()
env["FLASK_APP"] = "main.py"
env["FLASK_ENV"] = "development"

# Spustenie Flasku
subprocess.check_call([python_bin, "-m", "flask", "run", "--debug"], env=env)

print("\n==========================================")
print("Flask server bol ukonceny.")
print("==========================================")
input("Stlac lubovolnu klavesu pre zatvorenie okna...")