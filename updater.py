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

# ------------------ Updater settings ------------------
MAIN_SCRIPT = "trc to csv.py"
LOCAL_VERSION_FILE = "version.txt"

URLS = {
    MAIN_SCRIPT: "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/trc%20to%20csv.py",
    "updater.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/updater.py",
    "version.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/version.txt",
    "can_error_reference.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/can_error_reference.txt"
}

# ------------------ Version handling ------------------
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

# ------------------ File download ------------------
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

# ------------------ Run main script ------------------
def run_main():
    print("🔄 Launching main script...")
    subprocess.Popen([sys.executable, MAIN_SCRIPT])
    sys.exit(0)

# ------------------ Ask user for update ------------------
def ask_user_update():
    root = tk.Tk()
    root.withdraw()
    return messagebox.askyesno(
        "Update Available",
        "🚀 A new update is available.\nDo you want to update now?"
    )

# ------------------ Updater logic ------------------
def main():
    local_version = read_local_version()
    remote_version = fetch_remote_version() or local_version

    print(f"Local version: {local_version}")
    print(f"Remote version: {remote_version}")

    files_to_download = []

    # If version changed → download all
    if remote_version != local_version:
        files_to_download = list(URLS.keys())
        user_agreed = ask_user_update()
        if not user_agreed:
            print("⏩ Skipping update by user choice.")
            files_to_download = []  # skip downloading everything
    else:
        user_agreed = False  # no need to ask
        # Version same → check for missing files
        for fname in URLS.keys():
            if not os.path.exists(fname):
                files_to_download.append(fname)

    # Download files
    if files_to_download:
        print("⬇️ Downloading files...")
        for fname in files_to_download:
            download_file(URLS[fname], fname)

        # Update version.txt only if version changed
        if remote_version != local_version and user_agreed:
            with open(LOCAL_VERSION_FILE, "w") as f:
                f.write(remote_version)

        print("✅ Update complete.")
    else:
        print("✅ All files are up to date.")

    run_main()

if __name__ == "__main__":
    main()
