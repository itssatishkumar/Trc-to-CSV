import os
import sys
import subprocess

# ------------------ Ensure required packages ------------------
def ensure_package(pkg_name, import_name=None):
    import_name = import_name or pkg_name
    try:
        __import__(import_name)
    except ImportError:
        print(f"⚡ Installing {pkg_name}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])

# Only install packages that are actually on PyPI
ensure_package("requests")

# Now import safely
import requests
import tkinter as tk
from tkinter import messagebox

# ------------------ Updater logic ------------------
MAIN_SCRIPT = "trc to csv.py"
LOCAL_VERSION_FILE = "version.txt"

URLS = {
    MAIN_SCRIPT: "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/refs/heads/main/trc%20to%20csv.py",
    "updater.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/refs/heads/main/updater.py",
    "version.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/refs/heads/main/version.txt"
}

def read_local_version():
    if not os.path.exists(LOCAL_VERSION_FILE):
        return "0.0.0"
    try:
        with open(LOCAL_VERSION_FILE, "r") as f:
            return f.read().strip()
    except Exception:
        return "0.0.0"

def fetch_remote_version():
    try:
        r = requests.get(URLS["version.txt"], timeout=10)
        if r.status_code == 200:
            return r.text.strip()
    except Exception as e:
        print(f"❌ Could not fetch remote version: {e}")
    return None

def download_file(url, local):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            with open(local, "wb") as f:
                f.write(r.content)
            print(f"✅ Updated {local}")
            return True
        else:
            print(f"❌ Failed to fetch {url} ({r.status_code})")
    except Exception as e:
        print(f"❌ Error fetching {url}: {e}")
    return False

def run_main():
    print("🔄 Launching main script...")
    subprocess.Popen([sys.executable, MAIN_SCRIPT])
    sys.exit(0)

def ask_user_update():
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    return messagebox.askyesno("Update Available", "🚀 A new update is available.\nDo you want to update now?")

def main():
    local_version = read_local_version()
    remote_version = fetch_remote_version()

    if not remote_version:
        print("⚠️ Could not check remote version. Running current script.")
        run_main()

    print(f"Local version: {local_version}")
    print(f"Remote version: {remote_version}")

    if remote_version != local_version:
        if ask_user_update():
            print("⬇️ Updating files...")
            for fname, url in URLS.items():
                download_file(url, fname)

            with open(LOCAL_VERSION_FILE, "w") as f:
                f.write(remote_version)

            print("✅ Update complete.")
        else:
            print("⏩ Skipping update.")

    run_main()

if __name__ == "__main__":
    main()
