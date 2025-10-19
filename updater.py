import os
import sys
import subprocess
import requests
import tkinter as tk
from tkinter import messagebox

MAIN_SCRIPT = "trc to csv.py"
LOCAL_VERSION_FILE = "version.txt"

URLS = {
    MAIN_SCRIPT: "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/trc%20to%20csv.py",
    "updater.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/updater.py",
    "version.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/version.txt",
    "can_error_reference.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/can_error_reference.txt"
}

def read_local_version():
    if not os.path.exists(LOCAL_VERSION_FILE):
        return "0.0.0"
    try:
        with open(LOCAL_VERSION_FILE, "r") as f:
            return f.read().strip()
    except:
        return "0.0.0"

def fetch_remote_version():
    try:
        r = requests.get(URLS["version.txt"], timeout=10)
        if r.status_code == 200:
            return r.text.strip()
    except:
        return None
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
    subprocess.Popen([sys.executable, MAIN_SCRIPT])
    sys.exit(0)

def ask_user_update():
    root = tk.Tk()
    root.withdraw()
    return messagebox.askyesno("Update Available", "🚀 A new update is available.\nDo you want to update now?")

def main():
    local_version = read_local_version()
    remote_version = fetch_remote_version() or local_version

    print(f"Local version: {local_version}")
    print(f"Remote version: {remote_version}")

    # 1️⃣ Version update
    if remote_version != local_version:
        if ask_user_update():
            print("⬇️ Updating all files due to version change...")
            for fname, url in URLS.items():
                download_file(url, fname)
            with open(LOCAL_VERSION_FILE, "w") as f:
                f.write(remote_version)
            print(f"✅ Version updated to {remote_version}")

    # 2️⃣ Missing files check → always download if missing
    missing_files = [fname for fname in URLS if not os.path.exists(fname)]
    if missing_files:
        print("⬇️ Downloading missing files...")
        for fname in missing_files:
            download_file(URLS[fname], fname)
        print("✅ All missing files downloaded.")

    # 3️⃣ Run main
    run_main()

if __name__ == "__main__":
    main()
