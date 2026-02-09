import os
import re
import math
import subprocess
import sys
from collections import defaultdict
from mf4_to_trc import main as mf4_to_trc_main
from mf4_to_csv import main as mf4_to_csv_main
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
_TRC_LINE_RE_OLD = re.compile(
    r'^\s*\d+\)?\s+'
    r'([\d.]+)\s+'
    r'(Rx|Tx|Error)\s*'
    r'([0-9A-Fa-f]+)?\s*'
    r'\d*\s*'
    r'((?:[0-9A-Fa-f]{2}\s*)+)',
)

_TRC_LINE_RE_PCAN = re.compile(
    r'^\s*'
    r'(\d+)\s+'
    r'([\d.]+)\s+'
    r'([A-Za-z]{1,4})\s+'
    r'([0-9A-Fa-f]{3,8})\s+'
    r'(Rx|Tx|Error)\s+'
    r'(\d+)'
    r'(?:\s+(.*))?'
    r'$',
)


def _parse_trc_line(line: str):
    """Parse one TRC line.

    Supports:
    - Existing format: "<n>) <ms> Rx|Tx|Error <id> <dlc> <data...>"
    - PCAN-View format: "<n> <ms> DT <id> Rx|Tx <dlc> <data...>"

    Returns:
        (timestamp_s, frame_type, can_id_int, data_bytes) or None
    """
    match = _TRC_LINE_RE_OLD.search(line)
    if match:
        timestamp_s = float(match.group(1)) / 1000.0
        frame_type = match.group(2)
        can_id = int(match.group(3), 16) if match.group(3) else 0
        data_bytes = bytes(int(b, 16) for b in match.group(4).split())
        return timestamp_s, frame_type, can_id, data_bytes

    match = _TRC_LINE_RE_PCAN.search(line)
    if match:
        timestamp_s = float(match.group(2)) / 1000.0
        pcan_type = (match.group(3) or "").upper()
        frame_type = match.group(5)  # Rx|Tx|Error
        can_id = int(match.group(4), 16)
        try:
            dlc = int(match.group(6))
        except ValueError:
            dlc = 0

        remainder = match.group(7) or ""
        hex_tokens = re.findall(r'\b[0-9A-Fa-f]{2}\b', remainder)
        if dlc > 0:
            hex_tokens = hex_tokens[:dlc]
        data_bytes = bytes(int(b, 16) for b in hex_tokens)

        # Treat PCAN error rows as Error frames when present.
        if pcan_type in {"ER", "ERR", "ERROR"}:
            frame_type = "Error"

        return timestamp_s, frame_type, can_id, data_bytes

    return None

import cantools
from tqdm import tqdm
import requests
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from merge_csv import merge_csv_files

# ------------------ PATHS & URLS ------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

LOCAL_VERSION_FILE = os.path.join(BASE_DIR, "version.txt")
REMOTE_VERSION_URL = "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/version.txt"

URLS = {
    "trc to csv.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/trc%20to%20csv.py",
    "merge_csv.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/merge_csv.py",
    "updater.py": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/updater.py",
    "version.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/version.txt",
    "can_error_reference.txt": "https://raw.githubusercontent.com/itssatishkumar/Trc-to-CSV/main/can_error_reference.txt"
}

# ------------------ DBC SOURCES ------------------
DBC_URLS = {
    "CIP BMS-24X": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/CIP%20BMS-24X.dbc",
    "G2A nBMS": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/G2A%20nBMS.dbc",
    "G2B LR200 nBMS": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/G2B_LR200%20nBMS.dbc",
    "ION BMS": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/ION_BMS.dbc",
    "Marvel 3W (all variants)": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/Marvel_3W_all_variant.dbc",
    "Athena 4 / 5": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/Athena%204%265.dbc",
}


def _looks_like_html(text: str) -> bool:
    head = (text or "").lstrip()[:200].lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<head" in head


def _unwrap_semicolon_terminated_statements(text: str) -> str:
    """Fixes DBC files that were hard-wrapped mid-line.

    Some DBCs (especially long VAL_/CM_/BA_ lines) get wrapped with newlines,
    which makes them invalid for cantools. This reconstructs those statements
    by concatenating lines until the trailing ';' is found and quotes balance.
    """

    if not text:
        return text

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    starters = {
        "VAL_",
        "CM_",
        "BA_",
        "BA_DEF_",
        "BA_DEF_DEF_",
        "VAL_TABLE_",
        "SIG_VALTYPE_",
    }

    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        keyword = stripped.split(None, 1)[0] if stripped else ""

        if keyword in starters:
            buf = line.rstrip()
            while i + 1 < len(lines):
                # Stop if statement seems complete: ends with ';' and quotes are balanced.
                if buf.strip().endswith(";") and (buf.count('"') % 2 == 0):
                    break

                i += 1
                cont = lines[i].strip()
                # Preserve separation so tokens don't merge.
                buf = f"{buf} {cont}" if cont else f"{buf} "

            out.append(buf)
        else:
            out.append(line)

        i += 1

    return "\n".join(out)


def fetch_and_load_dbc_from_url(dbc_url: str):
    resp = requests.get(dbc_url, timeout=15)
    resp.raise_for_status()

    # Prefer Requests' decoded text but guard against bad encodings.
    if not resp.encoding:
        try:
            resp.encoding = resp.apparent_encoding
        except Exception:
            pass

    text = (resp.text or "").lstrip("\ufeff")
    if _looks_like_html(text):
        raise ValueError("Downloaded HTML instead of a DBC. The GitHub URL likely isn't a raw .dbc file.")

    text = _unwrap_semicolon_terminated_statements(text)
    return cantools.database.load_string(text, strict=False)

def select_dbc_file(root):
    """Popup to select a DBC source from a single dropdown.

    Returns:
        - One of the keys from DBC_URLS (str), or
        - A local .dbc file path (str) when "Load Custom DBC..." is used, or
        - None if the dialog is cancelled/closed.
    """

    custom_label = "Load Custom DBC..."
    dbc_options = list(DBC_URLS.keys()) + [custom_label]
    selection = {"value": None}

    win = tk.Toplevel(root)
    win.title("Select DBC Source")
    win.resizable(False, False)

    popup_w, popup_h = 460, 160
    try:
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = max(0, (sw - popup_w) // 2)
        y = max(0, (sh - popup_h) // 3)
        win.geometry(f"{popup_w}x{popup_h}+{x}+{y}")
    except Exception:
        win.geometry(f"{popup_w}x{popup_h}")

    def close_without_selection():
        selection["value"] = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", close_without_selection)
    win.bind("<Escape>", lambda _e: close_without_selection())

    container = ttk.Frame(win, padding=16)
    container.pack(fill="both", expand=True)

    ttk.Label(container, text="Select DBC:", font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w")

    choice_var = tk.StringVar(value="")
    combo = ttk.Combobox(
        container,
        textvariable=choice_var,
        values=dbc_options,
        state="readonly",
        width=42,
        font=("Segoe UI", 11),
    )
    combo.grid(row=1, column=0, columnspan=2, sticky="we", pady=(8, 12))
    combo.current(0)

    container.grid_columnconfigure(0, weight=1)

    def choose_custom_and_close():
        path = filedialog.askopenfilename(
            filetypes=[("DBC files", "*.dbc"), ("All files", "*.*")],
            parent=win,
            title="Select a DBC file",
        )
        if path:
            selection["value"] = path
            win.destroy()
        else:
            # Reset back to first built-in option if user cancels
            combo.current(0)

    def on_ok():
        value = (choice_var.get() or "").strip()
        if not value:
            return
        if value == custom_label:
            choose_custom_and_close()
            return
        selection["value"] = value
        win.destroy()

    def on_change(_event=None):
        # If user selects custom, immediately open file dialog
        if choice_var.get() == custom_label:
            choose_custom_and_close()

    combo.bind("<<ComboboxSelected>>", on_change)

    buttons = ttk.Frame(container)
    buttons.grid(row=2, column=0, columnspan=2, sticky="e")
    ttk.Button(buttons, text="Cancel", command=close_without_selection).pack(side="right", padx=(8, 0))
    ttk.Button(buttons, text="OK", command=on_ok).pack(side="right")

    # Make sure it shows and gets focus
    win.update_idletasks()
    try:
        win.deiconify()
    except Exception:
        pass
    win.lift()
    try:
        win.attributes("-topmost", True)
        win.after(250, lambda: win.attributes("-topmost", False))
    except Exception:
        pass
    try:
        combo.focus_set()
    except Exception:
        pass

    win.grab_set()
    root.wait_window(win)
    return selection["value"]


# Backwards-compatible name (older code paths may still call this)
def select_dbc_dialog(root):
    return select_dbc_file(root)
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
            parsed = _parse_trc_line(line)
            if parsed:
                offset_ms = parsed[0] * 1000.0
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
        alert.title("⚠️ CAN BUS Error Summary")
        alert.geometry("800x600")
        alert.configure(bg="#1e1e1e")

        tk.Label(alert, text="⚠️ CAN BUS Error Summary", fg="white", bg="#1e1e1e",
                 font=("Segoe UI", 16, "bold")).pack(pady=(10, 5))

        text_area = scrolledtext.ScrolledText(alert, wrap=tk.WORD, bg="#252526", fg="white",
                                              font=("Consolas", 11), insertbackground="white")
        text_area.pack(fill="both", expand=True, padx=10, pady=10)
        text_area.insert(tk.END, "Detected CAN BUS errors:\n\n")

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

SPECIAL_TIME_CAN_ID = 0x405

# ------------------ TRC DECODING ------------------
def parse_trc_file(trc_file, dbc):
    # Pre-seed all signal columns from the loaded DBC so columns are not dropped
    # even if a given CAN ID never appears in the TRC.
    signal_names = set()
    signal_to_can_id = {}  # signal name -> message frame_id
    try:
        for msg in getattr(dbc, "messages", []) or []:
            frame_id = getattr(msg, "frame_id", None)
            if frame_id == SPECIAL_TIME_CAN_ID:
                continue
            for sig in getattr(msg, "signals", []) or []:
                sig_name = getattr(sig, "name", None)
                if not sig_name:
                    continue
                signal_names.add(sig_name)
                # If the same signal name exists in multiple messages, keep the first mapping
                # (the codebase historically assumes signal names are unique).
                signal_to_can_id.setdefault(sig_name, frame_id)
    except Exception:
        # If anything unexpected happens, fall back to discovering signals dynamically.
        signal_names = set()
        signal_to_can_id = {}

    decoded_rows = []
    last_known_values = {}  # signal name -> last value
    last_seen_time = {}  # can_id -> last timestamp (seconds)
    error_frames = []

    with open(trc_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    for line in tqdm(lines, desc="🔍 Decoding", unit="lines"):
        try:
            parsed = _parse_trc_line(line)
            if not parsed:
                continue

            timestamp, frame_type, can_id, data_bytes = parsed

            if frame_type == "Error":
                if len(data_bytes) < 4:
                    continue
                direction = "Sending" if data_bytes[0] == 0 else "Receiving"
                bit_pos = str(data_bytes[1])
                rx = data_bytes[2]
                tx = data_bytes[3]
                etype = {1:"Bit Error",2:"Form Error",4:"Stuff Error",8:"Other Error"}.get(can_id,"Unknown")
                error_frames.append({"type":etype,"direction":direction,"bit_pos":bit_pos,"rx":rx,"tx":tx})

            # --------------------------------------------------
            # SPECIAL HANDLING FOR 0x405 (TIME/DATE FRAME)
            # --------------------------------------------------
            if can_id == SPECIAL_TIME_CAN_ID and len(data_bytes) >= 6:

                hex_bytes = [f"{b:02X}" for b in data_bytes]

                # TIME = Byte 0,1,2
                time_str = f"{hex_bytes[0]}:{hex_bytes[1]}:{hex_bytes[2]}"

                # DATE = Byte 3,4,5
                date_str = f"{hex_bytes[3]}:{hex_bytes[4]}:{hex_bytes[5]}"

                last_known_values["TIME"] = time_str
                last_known_values["DATE"] = date_str

                signal_names.add("TIME")
                signal_names.add("DATE")

                signal_to_can_id["TIME"] = can_id
                signal_to_can_id["DATE"] = can_id

                last_seen_time[can_id] = timestamp

            else:
                message = dbc.get_message_by_frame_id(can_id)
                if message:
                    decoded = message.decode(data_bytes)
                    last_seen_time[can_id] = timestamp
                    for sig, val in decoded.items():
                        last_known_values[sig] = val
                        signal_names.add(sig)
                        signal_to_can_id.setdefault(sig, can_id)

            # Build row with timeout logic
            row = {"Time (s)": round(timestamp, 6)}
            for sig in signal_names:
                # Per-CAN-ID staleness rule: if the message (frame id) hasn't appeared
                # in >1.0s, then all its signals are written as "NA".
                sig_can_id = signal_to_can_id.get(sig)
                seen_time = last_seen_time.get(sig_can_id)
                if seen_time is not None and (timestamp - seen_time) <= 1.0 and sig in last_known_values:
                    row[sig] = last_known_values[sig]
                else:
                    row[sig] = "NA"
            decoded_rows.append(row)
        except Exception:
            continue

    # ------------------ COLUMN ORDER FIX ------------------
    ordered_signals = sorted(signal_names)
    # Force DATE and TIME to be adjacent and first (after Time (s))
    if "DATE" in ordered_signals:
        ordered_signals.remove("DATE")
    if "TIME" in ordered_signals:
        ordered_signals.remove("TIME")
        ordered_signals = ["DATE", "TIME"] + ordered_signals

    return decoded_rows, ["Time (s)"] + ordered_signals, error_frames

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


def _add_cip_derived_values(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived columns for the CIP BMS-24X DBC.

    Note: This must run on the numeric dataframe (before adding the units row).
    """

    df = df.copy()

    cell_cols = [
        "CMU_1_CV1","CMU_1_CV2","CMU_1_CV3","CMU_1_CV4",
        "CMU_1_CV5","CMU_1_CV6","CMU_1_CV7","CMU_1_CV8",
        "CMU_1_CV9",
        "CMU_2_CV1","CMU_2_CV2","CMU_2_CV3","CMU_2_CV4",
        "CMU_2_CV5","CMU_2_CV6","CMU_2_CV7","CMU_2_CV8",
        "CMU_2_CV9",
    ]

    temp_cols = [
        "Temperature_1","Temperature_2","Temperature_3",
        "Temperature_4","Temperature_5","Temperature_6",
    ]

    existing_cell_cols = [c for c in cell_cols if c in df.columns]
    existing_temp_cols = [c for c in temp_cols if c in df.columns]

    if existing_cell_cols:
        cell_vals = df[existing_cell_cols].apply(pd.to_numeric, errors="coerce")
        df[" Max. Cell Voltage [mV]"] = cell_vals.max(axis=1)
        df[" Min. Cell Voltage [mV]"] = cell_vals.min(axis=1)

    if existing_temp_cols:
        temp_vals = df[existing_temp_cols].apply(pd.to_numeric, errors="coerce")
        df["Temp_Max_degC"] = temp_vals.max(axis=1)
        df["Temp_Min_degC"] = temp_vals.min(axis=1)

    return df

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
    trc_files = list(filedialog.askopenfilenames(filetypes=[("TRC files", "*.trc")]))
    if not trc_files:
        print("❌ No TRC files selected.")
        return

    print(f"✅ Selected {len(trc_files)} TRC file(s)")

    # --- DBC selection dialog ---
    print("\n📁 Please select the DBC source")
    dbc_source = select_dbc_file(root)
    if not dbc_source:
        print("❌ No DBC source selected.")
        return

    is_cip_dbc = (dbc_source == "CIP BMS-24X")

    try:
        if dbc_source in DBC_URLS:
            print(f"🌐 Fetching DBC from GitHub: {dbc_source}")
            dbc_url = DBC_URLS[dbc_source]
            dbc = fetch_and_load_dbc_from_url(dbc_url)
        else:
            print(f"📁 Loading your DBC file: {dbc_source}")
            dbc = cantools.database.load_file(dbc_source)
    except Exception as e:
        print(f"❌ Failed to load DBC: {e}")
        return

    # ---------------- Time resolution selection ----------------
    interval_var = tk.DoubleVar(value=0)
    interval_win = tk.Toplevel(root)
    interval_win.title("⏱️ Select Time Resolution")
    tk.Label(interval_win, text="Select the time resolution for the output CSV:", font=("Segoe UI", 12)).pack(pady=10)

    def set_interval(val):
        interval_var.set(val)
        interval_win.destroy()

    tk.Button(interval_win, text="Default TRC timestamps", command=lambda: set_interval(0), width=25).pack(pady=5)
    tk.Button(interval_win, text="Resample every 300 ms", command=lambda: set_interval(0.3), width=25).pack(pady=5)
    tk.Button(interval_win, text="Resample every 500 ms", command=lambda: set_interval(0.5), width=25).pack(pady=5)
    tk.Button(interval_win, text="Resample every 1000 ms", command=lambda: set_interval(1), width=25).pack(pady=5)
    interval_win.grab_set()
    root.wait_window(interval_win)

    selected_interval = float(interval_var.get())

    # If multiple TRCs are selected, sort them by $STARTTIME from the TRC header
    ordered_trc_files = list(trc_files)
    if len(trc_files) > 1:
        try:
            infos = [extract_trc_info(f) for f in trc_files]
            infos = [i for i in infos if i.get("start_timestamp") is not None]
            if len(infos) == len(trc_files):
                infos.sort(key=lambda x: x["start_timestamp"])
                ordered_trc_files = [i["file"] for i in infos]

                print("\n🕒 TRC files sorted by start time:")
                for i in infos:
                    print(f"- {os.path.basename(i['file']):20} → $STARTTIME = {i['start_timestamp']} → {i['start_time_str']}")
        except Exception as e:
            print(f"⚠️ Could not sort TRC files by start time, using selection order. Reason: {e}")

    # ---------------- Single TRC: keep threaded behavior ----------------
    if len(ordered_trc_files) == 1:
        trc_path = ordered_trc_files[0]
        print(f"\n🔍 Decoding TRC file: {os.path.basename(trc_path)}")

        def on_decode_done(rows, columns, errors):
            if errors:
                show_error_alert(root, errors)

            if not rows:
                print("❌ No data decoded.")
                return

            df = pd.DataFrame(rows)
            df = df.reindex(columns=columns)

            # ----------------- CIP-derived values (no filtering) -----------------
            derived_units = {}
            if is_cip_dbc:
                df = _add_cip_derived_values(df)
                derived_units = {
                    " Max. Cell Voltage [mV]": "mV",
                    " Min. Cell Voltage [mV]": "mV",
                    "Temp_Max_degC": "degC",
                    "Temp_Min_degC": "degC",
                }

            # ----------------- Add units -----------------
            unit_map = {sig.name: sig.unit or "" for msg in dbc.messages for sig in msg.signals}

            def find_unit_for_col(col_name):
                if col_name in derived_units:
                    return derived_units[col_name]
                return unit_map.get(col_name, "")

            unit_row = ["s" if c == "Time (s)" else find_unit_for_col(c) for c in df.columns]
            df_units = pd.DataFrame([unit_row], columns=df.columns)
            df = pd.concat([df_units, df], ignore_index=True)

            # ----------------- Resample -----------------
            if selected_interval > 0:
                df = resample_dataframe(df, selected_interval)

            base_path = os.path.splitext(trc_path)[0] + "_decoded"
            print("\n💡 Starting CSV writing...")
            csv_paths = write_large_csv(df, base_path)
            print("✅ CSV writing complete!")

            if csv_paths and messagebox.askyesno("Open CSV?", f"Do you want to open the first CSV file?\n{csv_paths[0]}"):
                if os.name == "nt":
                    os.startfile(csv_paths[0])

        # Run decoding synchronously for single-file mode so the function
        # doesn't return and destroy the Tk root before the worker completes.
        try:
            rows, columns, errors = parse_trc_file(trc_path, dbc)
            on_decode_done(rows, columns, errors)
        except Exception as e:
            print(f"❌ Failed to decode {trc_path}: {e}")
        return

    # ---------------- Multiple TRCs: per‑file CSV + merge ----------------
    print("\n🔍 Decoding multiple TRC files one by one...")

    all_error_frames = []
    all_csv_paths = []

    for trc_path in ordered_trc_files:
        print(f"\n▶ Processing {os.path.basename(trc_path)}")
        try:
            rows, columns, errors = parse_trc_file(trc_path, dbc)
        except Exception as e:
            print(f"❌ Failed to decode {trc_path}: {e}")
            continue

        all_error_frames.extend(errors or [])

        if not rows:
            print(f"❌ No data decoded for {trc_path}. Skipping.")
            continue

        df = pd.DataFrame(rows)
        df = df.reindex(columns=columns)

        # ----------------- CIP-derived values (no filtering) -----------------
        derived_units = {}
        if is_cip_dbc:
            df = _add_cip_derived_values(df)
            derived_units = {
                " Max. Cell Voltage [mV]": "mV",
                " Min. Cell Voltage [mV]": "mV",
                "Temp_Max_degC": "degC",
                "Temp_Min_degC": "degC",
            }

        # ----------------- Add units -----------------
        unit_map = {sig.name: sig.unit or "" for msg in dbc.messages for sig in msg.signals}

        def find_unit_for_col(col_name):
            if col_name in derived_units:
                return derived_units[col_name]
            return unit_map.get(col_name, "")

        unit_row = ["s" if c == "Time (s)" else find_unit_for_col(c) for c in df.columns]
        df_units = pd.DataFrame([unit_row], columns=df.columns)
        df = pd.concat([df_units, df], ignore_index=True)

        # ----------------- Resample -----------------
        if selected_interval > 0:
            df = resample_dataframe(df, selected_interval)

        base_path = os.path.splitext(trc_path)[0] + "_decoded"
        print("💡 Writing CSV for this TRC...")
        csv_paths = write_large_csv(df, base_path)
        all_csv_paths.extend(csv_paths)

    if all_error_frames:
        show_error_alert(root, all_error_frames)

    if not all_csv_paths:
        print("❌ No CSV files were created from the selected TRCs.")
        return

    # ---------------- Merge all per‑TRC CSVs into one (with splitting) ----------------
    output_dir = os.path.dirname(all_csv_paths[0])
    final_csv = os.path.join(output_dir, "merged_decoded.csv")

    try:
        print("\n🧩 Merging all decoded CSV files into one or more CSVs (with row limit)...")
        merged_paths = merge_csv_files(
            all_csv_paths,
            final_csv,
            open_after=False,
            row_limit=1_000_000,
        )
    except Exception as e:
        print(f"❌ Failed to merge CSV files: {e}")
        return

    # ---------------- Delete temporary per‑TRC CSV files ----------------
    for path in all_csv_paths:
        try:
            os.remove(path)
            print(f"🗑️ Deleted temporary CSV: {path}")
        except OSError as e:
            print(f"⚠️ Could not delete temporary CSV {path}: {e}")

    # merged_paths may be None (older merge_csv_files behavior), so
    # fall back to the single final_csv path when needed.
    if isinstance(merged_paths, list) and merged_paths:
        first_csv = merged_paths[0]
        print(f"\n✅ Final merged CSV file(s) created. First file: {first_csv}")
    else:
        first_csv = final_csv
        print(f"\n✅ Final merged CSV created: {final_csv}")

    if messagebox.askyesno("Open merged CSV?", f"Do you want to open the first merged CSV file?\n{first_csv}"):
        if os.name == "nt":
            os.startfile(first_csv)

# ------------------ CHOICE MENU ------------------
def show_choice_menu(root):
    """Show menu to choose conversion type"""
    root.withdraw()
    
    choice_win = tk.Toplevel(root)
    choice_win.title("📊 Select Conversion Type")
    choice_win.geometry("420x360")
    choice_win.resizable(False, False)
    choice_win.grab_set()
    
    choice_var = tk.IntVar()
    
    tk.Label(
        choice_win,
        text="Select conversion type:",
        font=("Segoe UI", 14, "bold"),
        pady=10
    ).pack()

    # --- Existing Options ---
    tk.Button(
        choice_win,
        text="🚀 TRC to CSV",
        font=("Segoe UI", 12),
        width=28,
        height=2,
        command=lambda: (choice_var.set(1), choice_win.destroy())
    ).pack(pady=8)

    tk.Button(
        choice_win,
        text="📄 LOG to CSV (BUSMASTER)",
        font=("Segoe UI", 12),
        width=28,
        height=2,
        command=lambda: (choice_var.set(2), choice_win.destroy())
    ).pack(pady=8)

    # --- New Separator ---
    ttk.Separator(choice_win, orient='horizontal').pack(fill='x', pady=12)

    tk.Label(
        choice_win,
        text="Additional Conversions:",
        font=("Segoe UI", 11, "italic")
    ).pack()

    # --- New Options ---
    tk.Button(
        choice_win,
        text="🔁 MF4 to TRC",
        font=("Segoe UI", 12),
        width=28,
        height=2,
        command=lambda: (choice_var.set(3), choice_win.destroy())
    ).pack(pady=8)

    tk.Button(
        choice_win,
        text="📊 MF4 to CSV",
        font=("Segoe UI", 12),
        width=28,
        height=2,
        command=lambda: (choice_var.set(4), choice_win.destroy())
    ).pack(pady=8)

    choice_win.focus()
    root.wait_window(choice_win)

    return choice_var.get()

# ------------------ RUN ------------------
if __name__ == "__main__":
    for fname, url in URLS.items():
        path = os.path.join(BASE_DIR, fname)
        if not os.path.exists(path):
            print(f"⚡ Missing file detected: {fname}, downloading...")
            download_file(url, path)

    check_for_update()

    root = tk.Tk()
    root.withdraw()
    
    choice = show_choice_menu(root)
    
    if choice == 1:
        # TRC to CSV
        main(root)
        try:
            root.destroy()
        except Exception:
            pass

    elif choice == 2:
        # BUSMASTER LOG to CSV
        from busmaster_to_csv import main as busmaster_main
        root.deiconify()
        busmaster_main(root)
        root.mainloop()

    elif choice == 3:
        mf4_to_trc_main(root)
        root.destroy()

    elif choice == 4:
        mf4_to_csv_main(root)
        root.destroy()


    else:
        print("❌ No option selected.")
        root.destroy()

