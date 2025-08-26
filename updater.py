import os
import requests
import sys
import subprocess

MAIN_SCRIPT = "trc to csv.py"
UPDATER_SCRIPT = "updater.py"

URLS = {
    MAIN_SCRIPT: "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/refs/heads/main/trc%20to%20csv.py",
    UPDATER_SCRIPT: "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/refs/heads/main/updater.py",
    "version.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/refs/heads/main/version.txt"
}

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

def main():
    print("⬇️ Updating files...")
    for fname, url in URLS.items():
        download_file(url, fname)

    print("🔄 Restarting main script...")
    subprocess.Popen([sys.executable, MAIN_SCRIPT])
    sys.exit(0)

if __name__ == "__main__":
    main()
