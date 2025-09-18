import os
import re
import math
import subprocess
import sys

# ------------------ AUTO PACKAGE INSTALL ------------------
def ensure_package(pkg_name, import_name=None):
    """Check if package is installed; if not, install it."""
    import_name = import_name or pkg_name
    try:
        __import__(import_name)
    except ImportError:
        print(f"⚡ Installing {pkg_name}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])

# Required packages (tkinter comes with Python, no pip needed)
for pkg, imp in [("pandas", None), ("cantools", None), ("tqdm", None), ("requests", None)]:
    ensure_package(pkg, imp)

# ------------------ IMPORTS ------------------
import pandas as pd
import cantools
from tqdm import tqdm
import requests
from tkinter import Tk, filedialog

# ------------------ FIX: Ensure paths are relative to script ------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
LOCAL_VERSION_FILE = os.path.join(BASE_DIR, "version.txt")
REMOTE_VERSION_URL = "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/refs/heads/main/version.txt"
# ------------------------------------------------------------------------------

# ------------------ UPDATE CHECK ------------------
def get_local_version():
    if not os.path.exists(LOCAL_VERSION_FILE):
        return "0.0.0"
    with open(LOCAL_VERSION_FILE, "r") as f:
        return f.read().strip()

def get_remote_version():
    try:
        r = requests.get(REMOTE_VERSION_URL, timeout=5)
        if r.status_code == 200:
            return r.text.strip()
    except Exception:
        return None
    return None

def version_newer(remote, local):
    def parse(v): return tuple(map(int, (v.strip().split("."))))
    try:
        return parse(remote) > parse(local)
    except Exception:
        return False

def check_for_update():
    local = get_local_version()
    remote = get_remote_version()
    if remote and version_newer(remote, local):
        print(f"⚡ Update available: {local} → {remote}")
        print("➡️  Running updater...")
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "updater.py")])
        sys.exit(0)
    else:
        print("✅ You are running the latest version.")

# ------------------ TRC HANDLING ------------------
def extract_trc_info(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    file_version = None
    start_timestamp = None
    start_time_str = None
    header = []
    messages = []
    in_header = True

    for line in lines:
        if line.startswith(";$FILEVERSION="):
            file_version = line.split("=")[1].strip()
        elif line.startswith(";$STARTTIME="):
            try:
                start_timestamp = float(line.split("=")[1].strip())
            except ValueError:
                pass
        elif line.strip().startswith(";   Start time:"):
            start_time_str = line.strip().split(": ", 1)[1].strip()

        if in_header:
            header.append(line)
            if line.strip().startswith(";---+"):
                in_header = False
        else:
            messages.append(line)

    if not file_version or not start_timestamp:
        raise ValueError(f"Missing version or start time in: {filepath}")

    return {
        "file": filepath,
        "filename": os.path.basename(filepath),
        "version": file_version,
        "start_timestamp": start_timestamp,
        "start_time_str": start_time_str,
        "header": header,
        "messages": messages
    }

def merge_in_forced_order(trc_files):
    if len(trc_files) == 1:
        print("✅ Single TRC file provided. Skipping merge.")
        return trc_files[0]

    file_infos = [extract_trc_info(f) for f in trc_files]
    versions = set(info["version"] for info in file_infos)
    print(f"ℹ️ Found TRC versions in input: {', '.join(versions)}")

    file_infos.sort(key=lambda x: x["start_timestamp"])
    print("\n🕒 File Start Times (merge will follow this order):")
    for info in file_infos:
        print(f"- {info['filename']:20} → $STARTTIME = {info['start_timestamp']} → {info['start_time_str']}")

    primary_info = file_infos[0]
    primary_header = primary_info["header"]
    primary_start_timestamp = primary_info["start_timestamp"]
    primary_start_time_str = primary_info["start_time_str"]

    final_lines = []
    line_counter = 1
    global_start_time = primary_start_timestamp

    for info in file_infos:
        matched = 0
        for line in info["messages"]:
            match = re.search(
                r'^\s*\d+\)?\s+([\d.]+)\s+(?:Rx|Tx)?\s*([0-9A-Fa-f]+)?\s*\d*\s*((?:[0-9A-Fa-f]{2}\s*)+)',
                line
            )
            if match:
                try:
                    offset_ms = float(match.group(1))
                except ValueError:
                    continue
                abs_time = info["start_timestamp"] + (offset_ms / 1000.0)
                new_offset_ms = (abs_time - global_start_time) * 1000
                new_offset_str = f"{new_offset_ms:10.1f}"
                new_line = re.sub(r'^\s*\d+\)?\s+[\d.]+', f"{line_counter:6d}){new_offset_str}", line.strip())
                final_lines.append(new_line)
                line_counter += 1
                matched += 1
        print(f"✅ {info['filename']} — matched {matched} of {len(info['messages'])} lines")

    if not final_lines:
        raise ValueError("❌ Merge failed: No TRC messages extracted.")

    output_path = os.path.join(os.path.dirname(trc_files[0]), "Final_Merge_trc.trc")
    with open(output_path, "w", encoding="utf-8") as f:
        for line in primary_header:
            if line.startswith(";$STARTTIME="):
                f.write(f";$STARTTIME={primary_start_timestamp}\n")
            elif line.strip().startswith(";   Start time:"):
                f.write(f";   Start time: {primary_start_time_str}\n")
            elif line.strip().startswith(";   Generated by"):
                f.write(";   Merged by TRC Tool\n")
            else:
                f.write(line)
        f.write("\n")
        for line in final_lines:
            f.write(line + "\n")

    print(f"\n✅ Merged TRC saved at: {output_path}")
    return output_path

def parse_trc_file(trc_file, dbc):
    signal_names = set()
    decoded_rows = []
    last_known_values = {}
    file_version = None

    with open(trc_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    for line in lines:
        if line.startswith(";$FILEVERSION="):
            file_version = line.split("=")[1].strip()
            break

    for line in tqdm(lines, desc="🔍 Decoding", unit="lines"):
        try:
            if file_version == "1.1":
                match = re.search(
                    r'^\s*\d+\)\s+([\d.]+)\s+(Rx|Tx)\s+([0-9A-Fa-f]+)\s+\d+\s+((?:[0-9A-Fa-f]{2}\s*)+)',
                    line
                )
                if not match:
                    continue
                timestamp = float(match.group(1)) / 1000
                can_id = int(match.group(3), 16)
                data_bytes = bytes(int(b, 16) for b in match.group(4).split())

            elif file_version == "2.0":
                match = re.search(
                    r'^\s*\d+\s+([\d.]+)\s+\S+\s+([0-9A-Fa-f]+)\s+(Rx|Tx)\s+\d+\s+((?:[0-9A-Fa-f]{2}\s*)+)',
                    line
                )
                if not match:
                    continue
                timestamp = float(match.group(1)) / 1000
                can_id = int(match.group(2), 16)
                data_bytes = bytes(int(b, 16) for b in match.group(4).split())
            else:
                print("❌ Unsupported TRC file version.")
                return [], []

            message = dbc.get_message_by_frame_id(can_id)
            if not message:
                continue

            decoded = message.decode(data_bytes)
            signal_names.update(decoded.keys())
            last_known_values.update(decoded)

            row = {"Time (s)": round(timestamp, 6)}
            row.update(last_known_values)
            decoded_rows.append(row)

        except Exception:
            continue

    return decoded_rows, ["Time (s)"] + sorted(signal_names)

def write_large_csv(df, base_path):
    row_limit = 1_000_000
    total_rows = len(df)
    total_parts = math.ceil(total_rows / row_limit)
    paths = []

    print(f"\n💾 Writing decoded data to CSV ({total_parts} part(s))...")
    for i in range(total_parts):
        chunk = df.iloc[i * row_limit : (i + 1) * row_limit]
        suffix = "" if i == 0 else f"_part{i+1}"
        path = f"{base_path}{suffix}.csv"
        chunk.to_csv(path, index=False)
        paths.append(path)
        print(f"✅ Saved: {path}")

    return paths

def main():
    Tk().withdraw()
    print("📂 Please select one or more .trc files")
    trc_files = filedialog.askopenfilenames(filetypes=[("TRC files", "*.trc")])
    if not trc_files:
        print("❌ No TRC files selected.")
        return

    try:
        merged_path = merge_in_forced_order(trc_files)
    except Exception as e:
        print(f"❌ Merge failed: {e}")
        return

    print("\n📁 Please select the .dbc file")
    dbc_file = filedialog.askopenfilename(filetypes=[("DBC files", "*.dbc")])
    if not dbc_file:
        print("❌ No DBC file selected.")
        return

    try:
        dbc = cantools.database.load_file(dbc_file)
    except Exception as e:
        print(f"❌ Failed to load DBC: {e}")
        return

    print("\n🔍 Decoding merged TRC file...")
    rows, columns = parse_trc_file(merged_path, dbc)

    if not rows:
        print("❌ No data decoded.")
        return

    df = pd.DataFrame(rows)
    df = df.reindex(columns=columns)

    base_path = os.path.splitext(merged_path)[0] + "_decoded"
    write_large_csv(df, base_path)

if __name__ == "__main__":
    check_for_update()
    main()
