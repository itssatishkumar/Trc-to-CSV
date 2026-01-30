import os
import sys
import subprocess
import requests
import tkinter as tk
from tkinter import messagebox

# ------------------ Ensure required packages ------------------
def ensure_package(pkg_name, import_name=None):
    import_name = import_name or pkg_name
    try:
        __import__(import_name)
    except ImportError:
        print(f"⚡ Installing {pkg_name}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])

ensure_package("requests")

# ------------------ Updater logic ------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MAIN_SCRIPT = os.path.join(BASE_DIR, "trc to csv.py")
LOCAL_VERSION_FILE = os.path.join(BASE_DIR, "version.txt")

URLS = {
    MAIN_SCRIPT: "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/trc%20to%20csv.py",
    "merge_csv.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/merge_csv.py",
    "busmaster_to_csv.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/busmaster_to_csv.py",
    "updater.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/updater.py",
    "version.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/version.txt",
    "can_error_reference.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/can_error_reference.txt"
}

# ------------------ Version Handling ------------------
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

def ask_user_update(local_version, remote_version):
    root = tk.Tk()
    root.withdraw()
    return messagebox.askyesno(
        "Update Available",
        f"🚀 A new update is available.\nLocal version: {local_version}\nRemote version: {remote_version}\n\nDo you want to update now?"
    )

def run_main():
    print("🔄 Launching main script...")
    subprocess.Popen([sys.executable, MAIN_SCRIPT])
    sys.exit(0)

# ------------------ Main Updater Logic ------------------
def main():
    local_version = read_local_version()
    remote_version = fetch_remote_version() or local_version

    print(f"Local version: {local_version}")
    print(f"Remote version: {remote_version}")

    # 1️⃣ Download all missing files first
    missing_files = [fname for fname in URLS if not os.path.exists(os.path.join(BASE_DIR, fname))]
    if missing_files:
        print("⬇️ Downloading missing file(s)...")
        for fname in missing_files:
            download_file(URLS[fname], os.path.join(BASE_DIR, fname))
        print("✅ Missing files downloaded.")

    # 2️⃣ If version changed → ask user to update all
    if remote_version != local_version:
        if ask_user_update(local_version, remote_version):
            print("⬇️ Updating all files to new version...")
            for fname, url in URLS.items():
                download_file(url, os.path.join(BASE_DIR, fname))

            # Update version file
            with open(LOCAL_VERSION_FILE, "w") as f:
                f.write(remote_version)
            print("✅ Update complete.")
        else:
            print("⏩ Skipping update.")

    run_main()

if __name__ == "__main__":
    main()
