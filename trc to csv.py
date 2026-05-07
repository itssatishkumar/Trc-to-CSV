import os
import re
import csv
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
        frame_type = match.group(5)
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
        if pcan_type in {"ER", "ERR", "ERROR"}:
            frame_type = "Error"

        return timestamp_s, frame_type, can_id, data_bytes

    return None


import cantools
import requests
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

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

DBC_URLS = {
    "CIP BMS-24X": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/CIP%20BMS-24X.dbc",
    "G2A nBMS": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/G2A%20nBMS.dbc",
    "G2B LR200 nBMS": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/G2B_LR200%20nBMS.dbc",
    "ION BMS": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/ION_BMS.dbc",
    "Marvel 3W (all variants)": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/Marvel_3W_all_variant.dbc",
    "Athena 4 / 5": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/Athena%204%265.dbc",
}

SPECIAL_TIME_CAN_ID = 0x405


def _looks_like_html(text: str) -> bool:
    head = (text or "").lstrip()[:200].lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<head" in head


def _unwrap_semicolon_terminated_statements(text: str) -> str:
    if not text:
        return text
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    starters = {"VAL_", "CM_", "BA_", "BA_DEF_", "BA_DEF_DEF_", "VAL_TABLE_", "SIG_VALTYPE_"}
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        keyword = stripped.split(None, 1)[0] if stripped else ""
        if keyword in starters:
            buf = line.rstrip()
            while i + 1 < len(lines):
                if buf.strip().endswith(";") and (buf.count('"') % 2 == 0):
                    break
                i += 1
                cont = lines[i].strip()
                buf = f"{buf} {cont}" if cont else f"{buf} "
            out.append(buf)
        else:
            out.append(line)
        i += 1
    return "\n".join(out)


def fetch_and_load_dbc_from_url(dbc_url: str):
    resp = requests.get(dbc_url, timeout=15)
    resp.raise_for_status()
    if not resp.encoding:
        try:
            resp.encoding = resp.apparent_encoding
        except Exception:
            pass
    text = (resp.text or "").lstrip("\ufeff")
    if _looks_like_html(text):
        raise ValueError("Downloaded HTML instead of a DBC.")
    text = _unwrap_semicolon_terminated_statements(text)
    return cantools.database.load_string(text, strict=False)


def select_dbc_file(root):
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
    combo = ttk.Combobox(container, textvariable=choice_var, values=dbc_options,
                         state="readonly", width=42, font=("Segoe UI", 11))
    combo.grid(row=1, column=0, columnspan=2, sticky="we", pady=(8, 12))
    combo.current(0)
    container.grid_columnconfigure(0, weight=1)

    def choose_custom_and_close():
        path = filedialog.askopenfilename(
            filetypes=[("DBC files", "*.dbc"), ("All files", "*.*")],
            parent=win, title="Select a DBC file")
        if path:
            selection["value"] = path
            win.destroy()
        else:
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
        if choice_var.get() == custom_label:
            choose_custom_and_close()

    combo.bind("<<ComboboxSelected>>", on_change)
    buttons = ttk.Frame(container)
    buttons.grid(row=2, column=0, columnspan=2, sticky="e")
    ttk.Button(buttons, text="Cancel", command=close_without_selection).pack(side="right", padx=(8, 0))
    ttk.Button(buttons, text="OK", command=on_ok).pack(side="right")

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
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "updater.py")])
        sys.exit(0)
    else:
        print("✅ You are running the latest version.")


# ------------------ CAN ERROR REFERENCE ------------------
def load_can_errors(ref_file):
    errors = {}
    if not os.path.exists(ref_file):
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
        return trc_files[0]

    file_infos = [extract_trc_info(f) for f in trc_files]
    file_infos.sort(key=lambda x: x["start_timestamp"])

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
    agg = defaultdict(lambda: {"count": 0, "max_rx": 0, "max_tx": 0})
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
                "Bit Error": "#ff4d4d", "Form Error": "#ff884d",
                "Stuff Error": "#ffcc00", "Other Error": "#00b3b3",
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
            "Bit Error": "#ff4d4d", "Form Error": "#ff884d",
            "Stuff Error": "#ffcc00", "Other Error": "#00b3b3",
        }.items():
            text_area.tag_configure(err_type, foreground=color, font=("Consolas", 11, "bold"))

        text_area.config(state=tk.DISABLED)
        tk.Label(alert, text="🛠️ Recommended Action: Check wiring, CAN nodes, and 120Ω termination.",
                 fg="#99ff99", bg="#1e1e1e", font=("Segoe UI", 10, "italic")).pack(pady=(0, 10))
        tk.Button(alert, text="Close", command=alert.destroy, bg="#333", fg="white",
                  font=("Segoe UI", 11), relief="raised", width=12).pack(pady=(0, 10))
        alert.grab_set()
        alert.focus()
        alert.lift()

    root.after(100, _show)


# ------------------ SIGNAL ORDER ------------------
def get_signal_order(dbc, signal_names):
    order_map = {}
    for msg in dbc.messages:
        for sig in msg.signals:
            try:
                attr = sig.dbc.attributes.get("CSV_ORDER")
                if attr is not None:
                    order_map[sig.name] = attr.value
            except Exception:
                pass

    priority = []
    remaining = []
    for sig in signal_names:
        if sig in order_map:
            priority.append((order_map[sig], sig))
        else:
            remaining.append(sig)
    priority.sort(key=lambda x: x[0])
    return [s for _, s in priority] + sorted(remaining)


def _get_ordered_columns(dbc, signal_names):
    ordered = get_signal_order(dbc, signal_names)
    if "BMS_Firmware" in ordered:
        ordered.remove("BMS_Firmware")
    if "DATE" in ordered:
        ordered.remove("DATE")
    if "TIME" in ordered:
        ordered.remove("TIME")
    ordered = ["DATE", "TIME"] + ordered
    if "BMS_Firmware" in signal_names:
        ordered.append("BMS_Firmware")
    return ordered


# ==================== STREAMING DECODE ====================
# KEY CHANGES vs original:
#  1. `for line in f` instead of `f.readlines()` — no full file in RAM
#  2. Rows written directly to temp CSV via csv.writer — no rows list in RAM
#  3. Returns only (tmp_csv_path, error_frames) — no DataFrame in memory
#  4. Caller does resampling as a second pass over the CSV in chunks

def parse_trc_to_csv_streaming(trc_file: str, dbc, tmp_csv_path: str) -> list:
    """
    Stream-decode a TRC file directly to a CSV on disk.
    Never holds more than one row in memory at a time.
    Returns error_frames list only (no rows, no DataFrame).
    """

    # Build signal metadata from DBC (small — just names/IDs)
    signal_names = set()
    signal_to_can_id = {}
    try:
        for msg in getattr(dbc, "messages", []) or []:
            if getattr(msg, "frame_id", None) == SPECIAL_TIME_CAN_ID:
                continue
            for sig in getattr(msg, "signals", []) or []:
                name = getattr(sig, "name", None)
                if not name:
                    continue
                signal_names.add(name)
                signal_to_can_id.setdefault(name, msg.frame_id)
    except Exception:
        pass

    last_known_values = {}
    last_seen_time = {}
    error_frames = []
    columns_written = False
    col_order = None

    # ---- Count lines for tqdm without loading file ----
    print("📏 Counting lines...")
    total_lines = sum(1 for _ in open(trc_file, 'r', encoding='utf-8', errors='ignore'))
    print(f"   {total_lines:,} lines found")

    # ---- Pre-scan: detect BMS_Firmware before columns are locked ----
    print("🔎 Pre-scanning for firmware frame (0x7A1)...")
    with open(trc_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            parsed = _parse_trc_line(line)
            if parsed and parsed[2] == 0x7A1:
                data_bytes = parsed[3]
                if len(data_bytes) >= 4 and data_bytes[0] == 0x02:
                    fw_str = f"{data_bytes[1]:02d}.{data_bytes[2]:02d}.{data_bytes[3]:02d}"
                    last_known_values["BMS_Firmware"] = fw_str
                    signal_names.add("BMS_Firmware")
                    signal_to_can_id["BMS_Firmware"] = 0x7A1
                    print(f"   ✅ Found firmware: {fw_str}")
                break   # only need the first occurrence

    csv_fh = None
    writer = None

    try:
        with open(trc_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in _tqdm_iter(f, total=total_lines, desc="🔍 Decoding", unit="lines"):
                try:
                    parsed = _parse_trc_line(line)
                    if not parsed:
                        continue

                    timestamp, frame_type, can_id, data_bytes = parsed

                    # --- Special: firmware version ---
                    if can_id == 0x7A1 and len(data_bytes) >= 4 and data_bytes[0] == 0x02:
                        fw_str = f"{data_bytes[1]:02d}.{data_bytes[2]:02d}.{data_bytes[3]:02d}"
                        last_known_values["BMS_Firmware"] = fw_str
                        signal_names.add("BMS_Firmware")
                        signal_to_can_id["BMS_Firmware"] = can_id
                        last_seen_time[can_id] = timestamp

                    # --- Error frames ---
                    if frame_type == "Error":
                        if len(data_bytes) >= 4:
                            direction = "Sending" if data_bytes[0] == 0 else "Receiving"
                            bit_pos = str(data_bytes[1])
                            rx = data_bytes[2]
                            tx = data_bytes[3]
                            etype = {1: "Bit Error", 2: "Form Error", 4: "Stuff Error",
                                     8: "Other Error"}.get(can_id, "Unknown")
                            error_frames.append({"type": etype, "direction": direction,
                                                 "bit_pos": bit_pos, "rx": rx, "tx": tx})
                        continue

                    # --- TIME/DATE special frame ---
                    if can_id == SPECIAL_TIME_CAN_ID and len(data_bytes) >= 6:
                        hex_bytes = [f"{b:02X}" for b in data_bytes]
                        last_known_values["TIME"] = f"{hex_bytes[0]}:{hex_bytes[1]}:{hex_bytes[2]}"
                        last_known_values["DATE"] = f"{hex_bytes[3]}:{hex_bytes[4]}:{hex_bytes[5]}"
                        signal_names.update(["TIME", "DATE"])
                        signal_to_can_id.setdefault("TIME", can_id)
                        signal_to_can_id.setdefault("DATE", can_id)
                        last_seen_time[can_id] = timestamp
                    else:
                        # --- Normal DBC decode ---
                        try:
                            message = dbc.get_message_by_frame_id(can_id)
                            if message:
                                decoded = message.decode(data_bytes)
                                last_seen_time[can_id] = timestamp
                                for sig, val in decoded.items():
                                    last_known_values[sig] = val
                                    signal_names.add(sig)
                                    signal_to_can_id.setdefault(sig, can_id)
                        except Exception:
                            pass

                    # --- Open CSV writer on first data row (columns now known) ---
                    if not columns_written:
                        col_order = ["Time (s)"] + _get_ordered_columns(dbc, signal_names)
                        csv_fh = open(tmp_csv_path, 'w', newline='', encoding='utf-8')
                        writer = csv.writer(csv_fh)
                        writer.writerow(col_order)      # header
                        columns_written = True

                    # --- Build and write one row ---
                    row = [round(timestamp, 6)]
                    for sig in col_order[1:]:           # skip "Time (s)"
                        sig_can_id = signal_to_can_id.get(sig)
                        seen_time = last_seen_time.get(sig_can_id)
                        if (seen_time is not None
                                and (timestamp - seen_time) <= 1.0
                                and sig in last_known_values):
                            row.append(last_known_values[sig])
                        else:
                            row.append("NA")

                    writer.writerow(row)

                except Exception:
                    continue

    finally:
        if csv_fh:
            csv_fh.close()

    print(f"✅ Streaming decode complete → {tmp_csv_path}")
    return error_frames


def _tqdm_iter(iterable, total, desc, unit):
    """Thin tqdm wrapper so import is in one place."""
    from tqdm import tqdm
    return tqdm(iterable, total=total, desc=desc, unit=unit)


# ---- Second-pass: inject units row + optional resample (chunked, low RAM) ----

def inject_units_and_resample(
    tmp_csv_path: str,
    out_csv_path: str,
    dbc,
    signal_names: set,
    selected_interval: float,
    is_cip_dbc: bool,
    chunk_size: int = 100_000,
):
    """
    Read the raw decoded CSV in chunks.
    - Optionally forward-fill resample at `selected_interval` seconds.
    - Inject a units row as the very first row of the output.
    - Appends CIP derived columns if needed.
    Never loads the whole file into RAM.
    """

    unit_map = {sig.name: sig.unit or "" for msg in dbc.messages for sig in msg.signals}
    derived_units = {}
    if is_cip_dbc:
        derived_units = {
            " Max. Cell Voltage [mV]": "mV",
            " Min. Cell Voltage [mV]": "mV",
            "Temp_Max_degC": "degC",
            "Temp_Min_degC": "degC",
        }

    def get_unit(col):
        if col in derived_units:
            return derived_units[col]
        if col == "Time (s)":
            return "s"
        return unit_map.get(col, "")

    print("📝 Second pass: injecting units + writing final CSV...")

    # Read columns first (just header row — tiny)
    header_df = pd.read_csv(tmp_csv_path, nrows=0)
    columns = list(header_df.columns)

    # Add CIP derived columns to header if needed
    if is_cip_dbc:
        for c in [" Max. Cell Voltage [mV]", " Min. Cell Voltage [mV]",
                  "Temp_Max_degC", "Temp_Min_degC"]:
            if c not in columns:
                columns.append(c)

    unit_row = [get_unit(c) for c in columns]

    first_write = True
    carry_row = None   # last row of previous chunk for ffill continuity across chunks

    for chunk in pd.read_csv(tmp_csv_path, chunksize=chunk_size, dtype=str):

        if is_cip_dbc:
            chunk = _add_cip_derived_values_chunk(chunk)

        # Ensure all output columns exist
        for c in columns:
            if c not in chunk.columns:
                chunk[c] = "NA"
        chunk = chunk[columns]

        if selected_interval > 0:
            chunk, carry_row = _resample_chunk(chunk, selected_interval, carry_row)

        if first_write:
            # Write units row + first chunk with header
            units_df = pd.DataFrame([unit_row], columns=columns)
            out_df = pd.concat([units_df, chunk], ignore_index=True)
            out_df.to_csv(out_csv_path, index=False, mode='w')
            first_write = False
        else:
            # Append without header
            chunk.to_csv(out_csv_path, index=False, mode='a', header=False)

    print(f"✅ Final CSV written → {out_csv_path}")


def _resample_chunk(chunk: pd.DataFrame, interval_sec: float, carry_row) -> tuple:
    """
    Resample a single chunk with forward-fill.
    carry_row: last row from previous chunk (for ffill across chunk boundary).
    Returns (resampled_chunk, new_carry_row).
    """
    # Prepend carry row so ffill works at chunk boundary
    if carry_row is not None:
        chunk = pd.concat([carry_row, chunk], ignore_index=True)

    numeric_time = pd.to_numeric(chunk["Time (s)"], errors="coerce")
    chunk = chunk[numeric_time.notna()].copy()
    chunk["Time (s)"] = pd.to_numeric(chunk["Time (s)"])

    if chunk.empty:
        return chunk, carry_row

    chunk["_td"] = pd.to_timedelta(chunk["Time (s)"], unit='s')
    chunk.set_index("_td", inplace=True)
    chunk = chunk[~chunk.index.duplicated(keep='first')]

    resampled = chunk.resample(f"{int(interval_sec * 1000)}ms").ffill(limit=2)
    resampled.reset_index(inplace=True)
    resampled["Time (s)"] = resampled["_td"].dt.total_seconds()
    resampled.drop(columns=["_td"], inplace=True)

    new_carry = resampled.iloc[-1:].copy()
    return resampled, new_carry


def _add_cip_derived_values_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    cell_cols = [
        "CMU_1_CV1", "CMU_1_CV2", "CMU_1_CV3", "CMU_1_CV4",
        "CMU_1_CV5", "CMU_1_CV6", "CMU_1_CV7", "CMU_1_CV8", "CMU_1_CV9",
        "CMU_2_CV1", "CMU_2_CV2", "CMU_2_CV3", "CMU_2_CV4",
        "CMU_2_CV5", "CMU_2_CV6", "CMU_2_CV7", "CMU_2_CV8", "CMU_2_CV9",
    ]
    temp_cols = [
        "Temperature_1", "Temperature_2", "Temperature_3",
        "Temperature_4", "Temperature_5", "Temperature_6",
    ]
    existing_cell = [c for c in cell_cols if c in chunk.columns]
    existing_temp = [c for c in temp_cols if c in chunk.columns]
    if existing_cell:
        vals = chunk[existing_cell].apply(pd.to_numeric, errors="coerce")
        chunk[" Max. Cell Voltage [mV]"] = vals.max(axis=1)
        chunk[" Min. Cell Voltage [mV]"] = vals.min(axis=1)
    if existing_temp:
        vals = chunk[existing_temp].apply(pd.to_numeric, errors="coerce")
        chunk["Temp_Max_degC"] = vals.max(axis=1)
        chunk["Temp_Min_degC"] = vals.min(axis=1)
    return chunk


# ---- High-level per-TRC entry point (replaces old parse_trc_file + DataFrame work) ----

def decode_trc_to_final_csv(
    trc_path: str,
    dbc,
    selected_interval: float,
    is_cip_dbc: bool,
    output_csv_path: str,
) -> list:
    """
    Full pipeline for one TRC file:
      1. Stream-decode TRC → raw temp CSV  (no RAM spike)
      2. Inject units + resample → final CSV  (chunked, low RAM)
      3. Delete temp CSV
    Returns error_frames.
    """
    tmp_csv = trc_path + ".tmp_raw.csv"

    try:
        error_frames = parse_trc_to_csv_streaming(trc_path, dbc, tmp_csv)

        if not os.path.exists(tmp_csv) or os.path.getsize(tmp_csv) == 0:
            print(f"❌ No data decoded from {os.path.basename(trc_path)}")
            return error_frames

        # Collect signal_names from CSV header for ordered columns
        hdr = pd.read_csv(tmp_csv, nrows=0)
        signal_names = set(hdr.columns) - {"Time (s)"}

        inject_units_and_resample(
            tmp_csv_path=tmp_csv,
            out_csv_path=output_csv_path,
            dbc=dbc,
            signal_names=signal_names,
            selected_interval=selected_interval,
            is_cip_dbc=is_cip_dbc,
        )

    finally:
        if os.path.exists(tmp_csv):
            os.remove(tmp_csv)
            print(f"🗑️ Deleted temp CSV: {tmp_csv}")

    return error_frames


# ------------------ CSV WRITER (kept for compatibility) ------------------
def write_large_csv(df, base_path):
    row_limit = 1_000_000
    total_rows = len(df)
    total_parts = math.ceil(total_rows / row_limit)
    paths = []
    for i in range(total_parts):
        chunk = df.iloc[i * row_limit:(i + 1) * row_limit]
        suffix = "" if i == 0 else f"_part{i + 1}"
        path = f"{base_path}{suffix}.csv"
        chunk.to_csv(path, index=False)
        paths.append(path)
        print(f"✅ Saved: {path}")
    return paths


# ------------------ MAIN ------------------

def main(root):
    root.withdraw()
    print("📂 Please select one or more .trc files")
    trc_files = list(filedialog.askopenfilenames(filetypes=[("TRC files", "*.trc")]))
    if not trc_files:
        print("❌ No TRC files selected.")
        return

    print(f"✅ Selected {len(trc_files)} TRC file(s)")

    print("\n📁 Please select the DBC source")
    dbc_source = select_dbc_file(root)
    if not dbc_source:
        print("❌ No DBC source selected.")
        return

    is_cip_dbc = (dbc_source == "CIP BMS-24X")

    try:
        if dbc_source in DBC_URLS:
            print(f"🌐 Fetching DBC from GitHub: {dbc_source}")
            dbc = fetch_and_load_dbc_from_url(DBC_URLS[dbc_source])
        else:
            print(f"📁 Loading your DBC file: {dbc_source}")
            dbc = cantools.database.load_file(dbc_source)
    except Exception as e:
        print(f"❌ Failed to load DBC: {e}")
        return

    # Time resolution selection
    interval_var = tk.DoubleVar(value=0)
    interval_win = tk.Toplevel(root)
    interval_win.title("⏱️ Select Time Resolution")
    tk.Label(interval_win, text="Select the time resolution for the output CSV:",
             font=("Segoe UI", 12)).pack(pady=10)

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

    # Sort TRC files by start time
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
                    print(f"- {os.path.basename(i['file']):20} → {i['start_time_str']}")
        except Exception as e:
            print(f"⚠️ Could not sort TRC files: {e}")

    output_dir = os.path.dirname(ordered_trc_files[0])
    all_error_frames = []
    all_csv_paths = []

    # ---- Process each TRC file with streaming pipeline ----
    for trc_path in ordered_trc_files:
        print(f"\n▶ Processing {os.path.basename(trc_path)}")
        base = os.path.splitext(trc_path)[0]
        out_csv = base + "_decoded.csv"

        try:
            errors = decode_trc_to_final_csv(
                trc_path=trc_path,
                dbc=dbc,
                selected_interval=selected_interval,
                is_cip_dbc=is_cip_dbc,
                output_csv_path=out_csv,
            )
            all_error_frames.extend(errors or [])

            if os.path.exists(out_csv):
                all_csv_paths.append(out_csv)
            else:
                print(f"❌ No output CSV for {os.path.basename(trc_path)}")

        except Exception as e:
            print(f"❌ Failed to process {trc_path}: {e}")
            continue

    if all_error_frames:
        show_error_alert(root, all_error_frames)

    if not all_csv_paths:
        print("❌ No CSV files were created.")
        return

    # ---- Merge all decoded CSVs ----
    from merge_csv import merge_csv_files

    final_csv = os.path.join(output_dir, "merged_decoded.csv")
    try:
        print("\n🧩 Merging all decoded CSV files...")
        merged_paths = merge_csv_files(
            all_csv_paths,
            final_csv,
            open_after=False,
            row_limit=1_000_000,
        )
    except Exception as e:
        print(f"❌ Failed to merge CSV files: {e}")
        return

    # Clean up per-TRC decoded CSVs
    for path in all_csv_paths:
        try:
            os.remove(path)
            print(f"🗑️ Deleted temporary CSV: {path}")
        except OSError as e:
            print(f"⚠️ Could not delete {path}: {e}")

    first_csv = merged_paths[0] if isinstance(merged_paths, list) and merged_paths else final_csv
    print(f"\n✅ Final merged CSV: {first_csv}")

    if messagebox.askyesno("Open CSV?", f"Do you want to open the CSV file?\n{first_csv}"):
        if os.name == "nt":
            os.startfile(first_csv)


# ------------------ CHOICE MENU ------------------
def _read_version():
    try:
        version_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.txt")
        with open(version_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "unknown"
def show_choice_menu(root):
    root.withdraw()

    WIN_W, WIN_H = 480, 320
    BG = "#f0f2f8"
    CARD_BG = "#ffffff"
    CARD_HOVER = "#f5f7ff"
    BORDER = "#dde1ef"
    TITLE_COLOR = "#111827"
    SUBTITLE_COLOR = "#6b7280"
    FOOTER_COLOR = "#9ca3af"
    VERSION_BG = "#eef0f7"
    VERSION_FG = "#6b7280"
    BLUE = "#2563eb"
    BLUE_BADGE_BG = "#dbeafe"
    GREEN = "#16a34a"
    GREEN_BADGE_BG = "#dcfce7"
    CHEVRON = "#9ca3af"

    choice_var = tk.IntVar(value=0)

    # ✅ THIS LINE WAS MISSING
    win = tk.Toplevel(root)
    win.configure(highlightthickness=2, highlightbackground="black")

    win.title("Select Conversion Type")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.grab_set()

    try:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = (sw - WIN_W) // 2
        y = (sh - WIN_H) // 3
        win.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")
    except Exception:
        win.geometry(f"{WIN_W}x{WIN_H}")

    win.bind("<Escape>", lambda e: win.destroy())

    f_heading = ("Segoe UI", 16, "bold")
    f_tagline = ("Segoe UI", 10)
    f_label = ("Segoe UI", 12, "bold")
    f_sub = ("Segoe UI", 10)
    f_badge = ("Segoe UI", 8, "bold")
    f_footer = ("Segoe UI", 9)
    f_ver = ("Segoe UI", 8)

    outer = tk.Frame(win, bg=BG)
    outer.pack(fill="both", expand=True, padx=24, pady=(20, 10))

    tk.Label(outer, text="Select Conversion Type",
             font=f_heading, fg=TITLE_COLOR, bg=BG,
             anchor="w").pack(fill="x", pady=(0, 2))

    tk.Label(outer, text="Choose the format that best fits your needs.",
             font=f_tagline, fg=SUBTITLE_COLOR, bg=BG,
             anchor="w").pack(fill="x", pady=(0, 14))

    def _all_widgets(parent):
        result = []
        for child in parent.winfo_children():
            result.append(child)
            result.extend(_all_widgets(child))
        return result

    def make_card(parent, badge_text, badge_fg, badge_bg,
                  label, sublabel, value):

        border_frame = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        border_frame.pack(fill="x", pady=5)

        card = tk.Frame(border_frame, bg=CARD_BG, cursor="hand2")
        card.pack(fill="x")

        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill="x", padx=14, pady=12)

        badge = tk.Frame(inner, bg=badge_bg, width=44, height=44)
        badge.pack(side="left", padx=(0, 14))
        badge.pack_propagate(False)

        tk.Label(badge, text=badge_text,
                 font=f_badge, fg=badge_fg,
                 bg=badge_bg).place(relx=0.5, rely=0.5, anchor="center")

        text_block = tk.Frame(inner, bg=CARD_BG)
        text_block.pack(side="left", fill="x", expand=True)

        tk.Label(text_block, text=label,
                 font=f_label, fg=badge_fg,
                 bg=CARD_BG, anchor="w").pack(fill="x")

        tk.Label(text_block, text=sublabel,
                 font=f_sub, fg=SUBTITLE_COLOR,
                 bg=CARD_BG, anchor="w").pack(fill="x")

        tk.Label(inner, text="›",
                 font=("Segoe UI", 18),
                 fg=CHEVRON, bg=CARD_BG).pack(side="right")

        def on_enter(e):
            for w in _all_widgets(card):
                try: w.configure(bg=CARD_HOVER)
                except: pass
            border_frame.configure(bg=badge_fg)

        def on_leave(e):
            for w in _all_widgets(card):
                try: w.configure(bg=CARD_BG)
                except: pass
            badge.configure(bg=badge_bg)
            for w in _all_widgets(badge):
                try: w.configure(bg=badge_bg)
                except: pass
            border_frame.configure(bg=BORDER)

        def on_click(e):
            choice_var.set(value)
            win.destroy()

        for w in _all_widgets(card) + [card]:
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)

    make_card(outer, "CSV", BLUE, BLUE_BADGE_BG,
              "TRC to CSV", "PEAK / PCAN trace files", 1)

    make_card(outer, "LOG", GREEN, GREEN_BADGE_BG,
              "LOG to CSV", "BUSMASTER log files", 2)

    footer = tk.Frame(win, bg=BG)
    footer.pack(side="bottom", pady=(4, 12))

    tk.Label(footer, text="CAN Bus Decoder — ",
             font=f_footer, fg=FOOTER_COLOR,
             bg=BG).pack(side="left")

    pill = tk.Frame(footer, bg=VERSION_BG, padx=6, pady=2)
    pill.pack(side="left")

    tk.Label(pill, text=f"v{_read_version()}",
             font=f_ver, fg=VERSION_FG,
             bg=VERSION_BG).pack()

    win.focus()
    root.wait_window(win)
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
        main(root)
        try:
            root.destroy()
        except Exception:
            pass
    elif choice == 2:
        from busmaster_to_csv import main as busmaster_main
        root.deiconify()
        busmaster_main(root)
        root.mainloop()
    else:
        print("❌ No option selected.")
        root.destroy()
