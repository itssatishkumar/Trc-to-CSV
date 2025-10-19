import os
import sys
import subprocess
import requests
import tkinter as tk
from tkinter import messagebox

# ------------------ CONFIG ------------------
MAIN_SCRIPT = "trc to csv.py"
LOCAL_VERSION_FILE = "version.txt"
URLS = {
    MAIN_SCRIPT: "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/refs/heads/main/trc%20to%20csv.py",
    "updater.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/refs/heads/main/updater.py",
    "version.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/refs/heads/main/version.txt",
    "can_error_reference.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/refs/heads/main/can_error_reference.txt"
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------ VERSION CHECK ------------------
def read_local_version():
    path = os.path.join(BASE_DIR, LOCAL_VERSION_FILE)
    if not os.path.exists(path):
        return "0.0.0"
    with open(path, "r") as f:
        return f.read().strip()

def fetch_remote_version():
    try:
        r = requests.get(URLS["version.txt"], timeout=10)
        if r.status_code == 200:
            return r.text.strip()
    except Exception as e:
        print(f"❌ Could not fetch remote version: {e}")
    return None

# ------------------ DOWNLOAD ------------------
def download_file(url, filename):
    try:
        local_path = os.path.join(BASE_DIR, filename)
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            with open(local_path, "wb") as f:
                f.write(r.content)
            print(f"✅ Updated {filename} → {local_path}")
            return True
        else:
            print(f"❌ Failed to fetch {url} ({r.status_code})")
    except Exception as e:
        print(f"❌ Error fetching {url}: {e}")
    return False

# ------------------ MAIN SCRIPT LAUNCH ------------------
def run_main():
    main_path = os.path.join(BASE_DIR, MAIN_SCRIPT)
    if not os.path.exists(main_path):
        print(f"❌ Cannot find {MAIN_SCRIPT} in {BASE_DIR}")
        sys.exit(1)
    print("🔄 Launching main script...")
    subprocess.Popen([sys.executable, main_path])
    sys.exit(0)

# ------------------ ASK USER ------------------
def ask_user_update():
    root = tk.Tk()
    root.withdraw()
    return messagebox.askyesno(
        "Update Available", 
        "🚀 A new update is available.\nDo you want to update now?"
    )

# ------------------ MAIN ------------------
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
            print("⬇️ Downloading updated files...")
            for fname, url in URLS.items():
                download_file(url, fname)

            # Update local version
            with open(os.path.join(BASE_DIR, LOCAL_VERSION_FILE), "w") as f:
                f.write(remote_version)

            print("✅ Update complete. All files are in the folder:")
            print(f"   {BASE_DIR}")
        else:
            print("⏩ Skipping update.")

    run_main()

if __name__ == "__main__":
    main()

