import os
import re
import math
import subprocess
import sys
from collections import defaultdict
import threading

# ------------------ AUTO PACKAGE INSTALL ------------------
def ensure_package(pkg_name, import_name=None):
    import_name = import_name or pkg_name
    try:
        __import__(import_name)
    except ImportError:
        print(f"⚡ Installing {pkg_name}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])

for pkg, imp in [("pandas", None), ("cantools", None), ("tqdm", None), ("requests", None)]:
    ensure_package(pkg, imp)

# ------------------ IMPORTS ------------------
import pandas as pd
import cantools
from tqdm import tqdm
import requests
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

# ------------------ PATHS & URLS ------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

LOCAL_VERSION_FILE = os.path.join(BASE_DIR, "version.txt")
REMOTE_VERSION_URL = "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/version.txt"

URLS = {
    "trc to csv.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/trc%20to%20csv.py",
    "updater.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/updater.py",
    "version.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/version.txt",
    "can_error_reference.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/can_error_reference.txt"
}

# ------------------ HELPER FUNCTIONS ------------------
def download_file(url, local):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            with open(local, "wb") as f:
                f.write(r.content)
            print(f"✅ Downloaded {local}")
            return True
        else:
            print(f"❌ Failed to download {url} ({r.status_code})")
    except Exception as e:
        print(f"❌ Error downloading {url}: {e}")
    return False

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

# ------------------ CAN ERROR REFERENCE ------------------
def load_can_errors(ref_file):
    errors = {}
    if not os.path.exists(ref_file):
        print(f"❌ CAN error reference file not found: {ref_file}")
        return errors
    with open(ref_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                code, msg = line.split("|", 1)
                errors[code.strip()] = msg.strip()
    return errors

CAN_ERRORS = load_can_errors(os.path.join(BASE_DIR, "can_error_reference.txt"))

# ------------------ TRC PROCESSING ------------------
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
                r'^\s*\d+\)?\s+([\d.]+)\s+(?:Rx|Tx|Error)?\s*([0-9A-Fa-f]+)?\s*\d*\s*((?:[0-9A-Fa-f]{2}\s*)+)',
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

# ------------------ ERROR AGGREGATION ------------------
def aggregate_can_errors(error_frames):
    agg = defaultdict(lambda: {"count":0, "max_rx":0, "max_tx":0})
    for err in error_frames:
        key = (err["type"], err["direction"], err["bit_pos"])
        agg[key]["count"] += 1
        agg[key]["max_rx"] = max(agg[key]["max_rx"], err["rx"])
        agg[key]["max_tx"] = max(agg[key]["max_tx"], err["tx"])
    return agg

# ------------------ NON-BLOCKING ALERT ------------------
def show_error_alert(root, error_frames):
    if not error_frames:
        return
    def _show():
        agg = aggregate_can_errors(error_frames)
        alert = tk.Toplevel(root)
        alert.title("⚠️ CAN Error Summary")
        alert.geometry("800x600")
        alert.configure(bg="#1e1e1e")

        tk.Label(alert, text="⚠️ CAN Error Summary", fg="white", bg="#1e1e1e",
                 font=("Segoe UI", 16, "bold")).pack(pady=(10, 5))

        text_area = scrolledtext.ScrolledText(alert, wrap=tk.WORD, bg="#252526", fg="white",
                                              font=("Consolas", 11), insertbackground="white")
        text_area.pack(fill="both", expand=True, padx=10, pady=10)
        text_area.insert(tk.END, "Detected CAN errors:\n\n")

        for (etype, direction, bit_pos), info in agg.items():
            color = {
                "Bit Error": "#ff4d4d",
                "Form Error": "#ff884d",
                "Stuff Error": "#ffcc00",
                "Other Error": "#00b3b3",
            }.get(etype, "white")

            text_area.insert(tk.END, f"• Error Type: {etype}\n", (etype,))
            text_area.insert(tk.END, f"  Direction: {direction}\n", "blue")
            text_area.insert(tk.END, f"  Bit Position: {bit_pos}\n")
            text_area.insert(tk.END, f"  Occurrences: {info['count']}\n", "orange")
            text_area.insert(tk.END, f"  Max RX: {info['max_rx']} | Max TX: {info['max_tx']}\n")
            text_area.insert(tk.END, "-" * 70 + "\n", "dim")

        text_area.tag_configure("dim", foreground="#888")
        text_area.tag_configure("blue", foreground="#4da6ff")
        text_area.tag_configure("orange", foreground="#ffb84d")
        for err_type, color in {
            "Bit Error": "#ff4d4d",
            "Form Error": "#ff884d",
            "Stuff Error": "#ffcc00",
            "Other Error": "#00b3b3",
        }.items():
            text_area.tag_configure(err_type, foreground=color, font=("Consolas", 11, "bold"))

        text_area.config(state=tk.DISABLED)
        tk.Label(alert, text="🛠️ Recommended Action: Check wiring, CAN nodes, and 120Ω termination at both ends.",
                 fg="#99ff99", bg="#1e1e1e", font=("Segoe UI", 10, "italic")).pack(pady=(0, 10))
        tk.Button(alert, text="Close", command=alert.destroy, bg="#333", fg="white",
                  font=("Segoe UI", 11), relief="raised", width=12).pack(pady=(0, 10))

        alert.grab_set()
        alert.focus()
        alert.lift()
    root.after(100, _show)  # schedule on main thread

# ------------------ TRC DECODING ------------------
def parse_trc_file(trc_file, dbc):
    signal_names = set()
    decoded_rows = []
    last_known_values = {}
    error_frames = []

    with open(trc_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    for line in tqdm(lines, desc="🔍 Decoding", unit="lines"):
        try:
            match = re.search(
                r'^\s*\d+\)?\s+([\d.]+)\s+(Rx|Tx|Error)\s*([0-9A-Fa-f]+)?\s*\d*\s*((?:[0-9A-Fa-f]{2}\s*)+)',
                line
            )
            if not match:
                continue
            timestamp = float(match.group(1)) / 1000
            frame_type = match.group(2)
            can_id = int(match.group(3), 16) if match.group(3) else 0
            data_bytes = bytes(int(b, 16) for b in match.group(4).split())

            if frame_type == "Error":
                direction = "Sending" if data_bytes[0] == 0 else "Receiving"
                bit_pos = str(data_bytes[1])
                rx = data_bytes[2]
                tx = data_bytes[3]
                etype = {1:"Bit Error",2:"Form Error",4:"Stuff Error",8:"Other Error"}.get(can_id,"Unknown")
                error_frames.append({"type":etype,"direction":direction,"bit_pos":bit_pos,"rx":rx,"tx":tx})

            message = dbc.get_message_by_frame_id(can_id)
            if message:
                decoded = message.decode(data_bytes)
                signal_names.update(decoded.keys())
                last_known_values.update(decoded)

            row = {"Time (s)": round(timestamp, 6)}
            row.update(last_known_values)
            decoded_rows.append(row)
        except Exception:
            continue

    return decoded_rows, ["Time (s)"] + sorted(signal_names), error_frames

# ------------------ CSV WRITER ------------------
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

# ------------------ RESAMPLE FUNCTION (FIXED) ------------------
def resample_dataframe(df, interval_sec):
    df = df.copy()
    unit_row = df.iloc[0:1]
    df_numeric = df.iloc[1:].copy()

    df_numeric['Time (s)'] = pd.to_timedelta(df_numeric['Time (s)'].astype(float), unit='s')
    df_numeric.set_index('Time (s)', inplace=True)

    # --- FIX: remove duplicate timestamps before resample ---
    df_numeric = df_numeric[~df_numeric.index.duplicated(keep='first')]

    df_resampled = df_numeric.resample(f"{int(interval_sec*1000)}ms").ffill().reset_index()
    df_resampled['Time (s)'] = df_resampled['Time (s)'].dt.total_seconds()

    df_final = pd.concat([unit_row, df_resampled], ignore_index=True)
    return df_final

# ------------------ THREADED DECODE ------------------
def decode_trc_in_thread(root, merged_path, dbc, callback):
    def worker():
        rows, columns, errors = parse_trc_file(merged_path, dbc)
        root.after(0, lambda: callback(rows, columns, errors))
    threading.Thread(target=worker, daemon=True).start()

# ------------------ MAIN ------------------
def main(root):
    root.withdraw()
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

    interval_sec = tk.DoubleVar(value=0)
    interval_win = tk.Toplevel(root)
    interval_win.title("⏱️ Select Time Resolution")
    tk.Label(interval_win, text="Select the time resolution for the output CSV:", font=("Segoe UI", 12)).pack(pady=10)

    def set_interval(val):
        interval_sec.set(val)
        interval_win.destroy()

    tk.Button(interval_win, text="Default TRC timestamps", command=lambda: set_interval(0), width=25).pack(pady=5)
    tk.Button(interval_win, text="Resample every 300 ms", command=lambda: set_interval(0.3), width=25).pack(pady=5)
    tk.Button(interval_win, text="Resample every 1000 ms", command=lambda: set_interval(1), width=25).pack(pady=5)
    interval_win.grab_set()
    root.wait_window(interval_win)

    print("\n🔍 Decoding merged TRC file...")

    def on_decode_done(rows, columns, errors):
        if errors:
            show_error_alert(root, errors)

        if not rows:
            print("❌ No data decoded.")
            return

        df = pd.DataFrame(rows)
        df = df.reindex(columns=columns)

        # ----------------- Add units -----------------
        unit_map = {sig.name: sig.unit or "" for msg in dbc.messages for sig in msg.signals}
        def find_unit_for_col(col_name):
            return unit_map.get(col_name, "")

        unit_row = ["s" if c=="Time (s)" else find_unit_for_col(c) for c in df.columns]
        df_units = pd.DataFrame([unit_row], columns=df.columns)
        df = pd.concat([df_units, df], ignore_index=True)

        # ----------------- Resample -----------------
        if interval_sec.get() > 0:
            df = resample_dataframe(df, interval_sec.get())

        base_path = os.path.splitext(merged_path)[0] + "_decoded"
        print("\n💡 Starting CSV writing...")
        csv_paths = write_large_csv(df, base_path)
        print("✅ CSV writing complete!")

        if csv_paths and messagebox.askyesno("Open CSV?", f"Do you want to open the first CSV file?\n{csv_paths[0]}"):
            if os.name == "nt":
                os.startfile(csv_paths[0])

    decode_trc_in_thread(root, merged_path, dbc, on_decode_done)

# ------------------ RUN ------------------
if __name__ == "__main__":
    for fname, url in URLS.items():
        path = os.path.join(BASE_DIR, fname)
        if not os.path.exists(path):
            print(f"⚡ Missing file detected: {fname}, downloading...")
            download_file(url, path)

    check_for_update()

    root = tk.Tk()
    main(root)
    root.mainloop()

