import cantools
import csv
import re
import os
import sys
import math
import subprocess
from tkinter import filedialog, Tk, messagebox, ttk
import tkinter as tk
from collections import OrderedDict
from datetime import datetime, timedelta
import pandas as pd
import requests

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

from tqdm import tqdm
from merge_csv import merge_csv_files

# ------------------- PATHS & URLS -------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

DBC_URLS = {
    "CIP BMS-24X": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/CIP%20BMS-24X.dbc",
    "G2A nBMS": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/G2A%20nBMS.dbc",
    "G2B LR200 nBMS": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/G2B_LR200%20nBMS.dbc",
    "ION BMS": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/ION_BMS.dbc",
    "Marvel 3W (all variants)": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/Marvel_3W_all_variant.dbc",
    "Athena 4 / 5": "https://raw.githubusercontent.com/itssatishkumar/CAN-SCRIPT-LOGGER/main/Athena%204%265.dbc",
}

START_DT_RE = re.compile(
    r"\*{3}START DATE AND TIME\s+(\d{1,2}):(\d{1,2}):(\d{4})\s+"
    r"(\d{1,2}):(\d{1,2}):(\d{1,2}):(\d{1,4})\*{3}"
)

# Allow hours to be 1..N digits because BUSMASTER can output 31:07:17:2586 etc.
TIME_RE_FLEX = re.compile(r"^(?P<h>\d+):(?P<m>\d{2}):(?P<s>\d{2}):(?P<sub>\d{4,5})$")


# ------------------- DBC FUNCTIONS -------------------
def _looks_like_html(text: str) -> bool:
    head = (text or "").lstrip()[:200].lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<head" in head


def _unwrap_semicolon_terminated_statements(text: str) -> str:
    """Fixes DBC files that were hard-wrapped mid-line."""
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
        raise ValueError("Downloaded HTML instead of a DBC. The GitHub URL likely isn't a raw .dbc file.")

    text = _unwrap_semicolon_terminated_statements(text)
    return cantools.database.load_string(text, strict=False)


def select_dbc_file(root):
    """Popup to select a DBC source from a dropdown."""
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

    tk.Label(container, text="Choose a DBC source:", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))

    def on_select(value):
        selection["value"] = value
        win.destroy()

    dropdown = ttk.Combobox(container, values=dbc_options, state="readonly", width=50)
    dropdown.pack(anchor="w", pady=4)
    dropdown.bind("<<ComboboxSelected>>", lambda e: on_select(dropdown.get()))

    tk.Label(container, text="Or press Escape to cancel.", font=("Segoe UI", 10), foreground="gray").pack(anchor="w", pady=(8, 0))

    win.focus()
    root.wait_window(win)

    if selection["value"] == custom_label:
        custom_path = select_file(root, "Select your .dbc file", [("DBC Files", "*.dbc")])
        return custom_path
    return selection["value"]


def select_files(title, filetypes):
    root = Tk(); root.withdraw()
    paths = filedialog.askopenfilenames(title=title, filetypes=filetypes)
    root.destroy()
    return list(paths)

def select_file(root, title, filetypes):
    root.withdraw()
    path = filedialog.askopenfilename(title=title, filetypes=filetypes)
    root.deiconify()
    return path

def save_file(title, defaultextension=".csv", filetypes=[("CSV files", "*.csv")]):
    root = Tk(); root.withdraw()
    path = filedialog.asksaveasfilename(title=title, defaultextension=defaultextension, filetypes=filetypes)
    root.destroy()
    return path


def _parse_start_dt_from_line(line: str):
    m = START_DT_RE.search(line.strip())
    if not m:
        return None
    d, mo, y, hh, mm, ss, ms = map(int, m.groups())
    ms = int(str(ms)[:3]) if ms > 999 else ms
    return datetime(y, mo, d, hh, mm, ss, ms * 1000)


def _parse_time_parts(time_str: str):
    mt = TIME_RE_FLEX.match(time_str)
    if not mt:
        return None
    h = int(mt["h"])
    m = int(mt["m"])
    s = int(mt["s"])
    sub = int(mt["sub"])
    if h < 0 or not (0 <= m <= 59) or not (0 <= s <= 59):
        return None
    return h, m, s, sub


def _sub_to_micro(sub: int) -> int:
    """
    BUSMASTER last field often behaves like 0.1ms ticks:
      7926 => 792.6 ms => 792600 us
    """
    return min(sub * 100, 999_999)


def _abs_dt(session_start: datetime,
            current_date_base: datetime,
            last_line_dt: datetime | None,
            time_str: str):
    """
    Returns:
      abs_dt, new_current_date_base
    Rules:
      - If HH <= 23: treat as time-of-day on current_date_base, with midnight rollover if time goes backwards.
      - If HH > 23: treat as elapsed time since session_start (no rollover logic needed).
    """
    parts = _parse_time_parts(time_str)
    if parts is None:
        return None, current_date_base

    h, m, s, sub = parts
    micro = _sub_to_micro(sub)

    if h <= 23:
        # time-of-day mode
        dt = datetime(current_date_base.year, current_date_base.month, current_date_base.day, h, m, s, micro)

        # midnight rollover: time went backwards compared to previous dt
        if last_line_dt is not None and dt < last_line_dt:
            current_date_base = current_date_base + timedelta(days=1)
            dt = datetime(current_date_base.year, current_date_base.month, current_date_base.day, h, m, s, micro)

        return dt, current_date_base

    # elapsed-time mode (HH can exceed 23)
    dt = session_start + timedelta(hours=h, minutes=m, seconds=s, microseconds=micro)
    return dt, current_date_base


def _extract_fields(parts):
    # <Time> <Tx/Rx> <Channel> <CAN ID> <Type> <DLC> <DataBytes...>
    if len(parts) < 7:
        return None

    time_str = parts[0]
    if _parse_time_parts(time_str) is None:
        return None

    can_id_tok = parts[3]
    if not can_id_tok.lower().startswith("0x"):
        return None

    try:
        dlc = int(parts[5])
    except Exception:
        return None

    if not (0 <= dlc <= 64):
        return None

    data_hex = parts[6:6 + dlc]
    if len(data_hex) != dlc:
        return None

    return time_str, can_id_tok, dlc, data_hex


def _get_start_time_from_file(log_path):
    """
    Extract the START DATE AND TIME from a BUSMASTER log file.
    Returns datetime object or None if not found.
    """
    try:
        with open(log_path, "r", errors="replace") as f:
            for line in f:
                maybe_start = _parse_start_dt_from_line(line)
                if maybe_start is not None:
                    return maybe_start
    except Exception:
        pass
    return None


# ------------------- DATAFRAME FUNCTIONS -------------------
def write_large_csv(df, base_path):
    """Write DataFrame to CSV, splitting if needed"""
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


def resample_dataframe(df, interval_sec):
    """Resample DataFrame to specified time interval.

    This function supports DataFrames created by `parse_log_file_to_dataframe` that
    include an `AbsDatetime` column (datetime objects) and an original `Time`
    column (BUSMASTER-style string). After resampling, the `Time` column is
    regenerated in the BUSMASTER format for each resampled timestamp.
    """
    df = df.copy()
    unit_row = df.iloc[0:1]
    df_numeric = df.iloc[1:].copy()

    # If we have absolute datetimes, resample by time index and regenerate BUSMASTER-style
    # timestamps in the `Time` column. Otherwise fall back to previous seconds-based behavior.
    if 'AbsDatetime' in df_numeric.columns:
        df_numeric['AbsDatetime'] = pd.to_datetime(df_numeric['AbsDatetime'])
        df_numeric.set_index('AbsDatetime', inplace=True)

        # Remove duplicate timestamps before resample
        df_numeric = df_numeric[~df_numeric.index.duplicated(keep='first')]

        df_resampled = df_numeric.resample(f"{int(interval_sec*1000)}ms").ffill().reset_index()

        # Recreate BUSMASTER-style Time strings from the resampled datetimes
        def _fmt_busmaster(dt, session_start=None, elapsed_mode=False):
            if elapsed_mode and session_start is not None:
                delta = dt - pd.to_datetime(session_start)
                total_seconds = int(delta.total_seconds())
                h = total_seconds // 3600
                m = (total_seconds % 3600) // 60
                s = total_seconds % 60
                sub = int(dt.microsecond // 100)
                return f"{h}:{m:02d}:{s:02d}:{sub:04d}"
            else:
                h = dt.hour
                m = dt.minute
                s = dt.second
                sub = int(dt.microsecond // 100)
                return f"{h:02d}:{m:02d}:{s:02d}:{sub:04d}"

        # If the original unit row specifies a session start, try to read it
        session_start = None
        elapsed_mode = False
        if 'SessionStart' in df_numeric.columns:
            session_start = df_numeric['SessionStart'].iloc[0]
            elapsed_mode = bool(df_numeric.get('ElapsedMode', False).iloc[0])

        df_resampled['Time'] = df_resampled['AbsDatetime'].apply(lambda dt: _fmt_busmaster(dt, session_start, elapsed_mode))

        # Drop helper columns from final output
        if 'SessionStart' in df_resampled.columns:
            df_resampled = df_resampled.drop(columns=['SessionStart'], errors='ignore')
        if 'ElapsedMode' in df_resampled.columns:
            df_resampled = df_resampled.drop(columns=['ElapsedMode'], errors='ignore')

        df_final = pd.concat([unit_row, df_resampled.drop(columns=['AbsDatetime'])], ignore_index=True)
        return df_final

    # Fallback: previous behavior using numeric seconds in 'Time (s)'
    df_numeric['Time (s)'] = pd.to_timedelta(df_numeric['Time (s)'].astype(float), unit='s')
    df_numeric.set_index('Time (s)', inplace=True)
    df_numeric = df_numeric[~df_numeric.index.duplicated(keep='first')]
    df_resampled = df_numeric.resample(f"{int(interval_sec*1000)}ms").ffill().reset_index()
    df_resampled['Time (s)'] = df_resampled['Time (s)'].dt.total_seconds()
    df_final = pd.concat([unit_row, df_resampled], ignore_index=True)
    return df_final


def parse_log_file_to_dataframe(
    log_path,
    dbc,
    id_mask=0x1FFFFFFF,
    carry_state_from=None,
):
    """Parse a single log file and return DataFrame with Time (s) column"""
    message_map = {msg.frame_id: msg for msg in dbc.messages}

    rows = {}  # abs_dt -> (abs_dt, time_str, snapshot)
    last_known = carry_state_from.copy() if carry_state_from else {}

    parsed = 0
    skipped = 0
    elapsed_mode = False  # Initialize elapsed_mode flag

    with open(log_path, "r", errors="replace") as f:
        session_start = None
        current_date_base = None
        last_line_dt = None

        # Read lines into memory and iterate with tqdm to show decoding progress
        lines = f.readlines()
        for raw in tqdm(lines, desc=f"🔍 Decoding {os.path.basename(log_path)}", unit="lines"):
            line = raw.strip()
            if not line:
                continue

            maybe_start = _parse_start_dt_from_line(line)
            if maybe_start is not None:
                session_start = maybe_start
                current_date_base = maybe_start
                last_line_dt = None
                continue

            if line.startswith("***"):
                continue

            if session_start is None or current_date_base is None:
                continue

            parts = line.split()
            fields = _extract_fields(parts)
            if fields is None:
                continue

            time_str, can_id_tok, dlc, data_hex = fields

            # Detect if the log encodes elapsed-time mode (HH > 23)
            parts_check = _parse_time_parts(time_str)
            if parts_check is not None and parts_check[0] > 23:
                elapsed_mode = True

            abs_dt, current_date_base = _abs_dt(
                session_start=session_start,
                current_date_base=current_date_base,
                last_line_dt=last_line_dt,
                time_str=time_str
            )
            if abs_dt is None:
                skipped += 1
                continue

            last_line_dt = abs_dt

            try:
                can_id = int(can_id_tok, 16) & id_mask
                data = bytes(int(b, 16) for b in data_hex)

                msg = message_map.get(can_id)
                if msg is None:
                    continue

                decoded = msg.decode(data)
                last_known.update(decoded)

                prev = rows.get(abs_dt)
                if prev is None:
                    snapshot = last_known.copy()
                else:
                    _, snapshot = prev
                    snapshot = snapshot.copy()

                snapshot.update(decoded)

                # Store reference time, original time string, and snapshot
                rows[abs_dt] = (abs_dt, time_str, snapshot)
                parsed += 1

            except Exception:
                skipped += 1
                continue

    # Convert to DataFrame
    ordered = OrderedDict((k, rows[k]) for k in sorted(rows.keys()))
    all_signals = sorted({sig for (_, _, snap) in ordered.values() for sig in snap.keys()})

    if not ordered:
        print(f"⚠️ No messages decoded from {log_path}")
        return None, last_known, session_start, elapsed_mode

    # Calculate output rows including original BUSMASTER time strings and absolute datetimes
    first_dt = list(ordered.keys())[0]
    data = []
    for abs_dt, (_, time_str, snap) in ordered.items():
        row = {"Time": time_str, "AbsDatetime": abs_dt, "SessionStart": session_start, "ElapsedMode": elapsed_mode}
        row.update({sig: snap.get(sig, "") for sig in all_signals})
        data.append(row)

    df = pd.DataFrame(data)
    
    # Add units row at the beginning
    unit_row = {"Time": "busmaster"}
    for sig in all_signals:
        unit_row[sig] = ""
    # include helper unit cells so columns align
    unit_row["AbsDatetime"] = ""
    unit_row["SessionStart"] = ""
    unit_row["ElapsedMode"] = ""
    
    df = pd.concat([pd.DataFrame([unit_row]), df], ignore_index=True)

    print(f"✅ Parsed {log_path}: {parsed} messages, {skipped} skipped")
    return df, last_known, session_start, elapsed_mode


def parse_logs_to_csv_with_sampling(
    log_paths,
    dbc,
    output_csv_path,
    sampling_interval=0,
):
    """Parse multiple logs, decode, optionally resample, and merge"""
    # Sort files by their START DATE AND TIME
    print("\n🔄 Sorting files by START DATE AND TIME...")
    files_with_start_time = []
    
    for log_path in log_paths:
        start_time = _get_start_time_from_file(log_path)
        if start_time is not None:
            files_with_start_time.append((start_time, log_path))
            print(f"  📄 {os.path.basename(log_path)}: {start_time}")
        else:
            print(f"  ⚠️ {os.path.basename(log_path)}: No START DATE AND TIME found, processing last")
            files_with_start_time.append((datetime.max, log_path))
    
    # Sort by start time
    files_with_start_time.sort(key=lambda x: x[0])
    sorted_log_paths = [path for _, path in files_with_start_time]
    
    print(f"\n✅ Files sorted by start time. Processing order:")
    for i, log_path in enumerate(sorted_log_paths, 1):
        print(f"  {i}. {os.path.basename(log_path)}")
    
    all_csv_paths = []
    last_known = {}

    for log_path in sorted_log_paths:
        print(f"\n📄 Processing: {log_path}")
        df, last_known, session_start, elapsed_mode = parse_log_file_to_dataframe(log_path, dbc, carry_state_from=last_known)
        
        if df is None:
            continue

        # Apply resampling if requested
        if sampling_interval > 0:
            print(f"⏱️ Resampling to {sampling_interval*1000}ms intervals...")
            # pass session_start and elapsed_mode so resampling can regenerate BUSMASTER-format timestamps
            df = resample_dataframe(df, sampling_interval)

        # Write to CSV (drop internal helper columns first)
        base_path = os.path.splitext(log_path)[0] + "_decoded"
        df_to_write = df.copy()
        for _col in ("AbsDatetime", "SessionStart", "ElapsedMode"):
            if _col in df_to_write.columns:
                del df_to_write[_col]
        csv_paths = write_large_csv(df_to_write, base_path)
        all_csv_paths.extend(csv_paths)

    if not all_csv_paths:
        print("❌ No CSV files were created.")
        return

    # Merge all CSVs
    output_dir = os.path.dirname(all_csv_paths[0])
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

    # Delete temporary CSVs
    for path in all_csv_paths:
        try:
            os.remove(path)
            print(f"🗑️ Deleted temporary CSV: {path}")
        except OSError as e:
            print(f"⚠️ Could not delete temporary CSV {path}: {e}")

    if isinstance(merged_paths, list) and merged_paths:
        first_csv = merged_paths[0]
        print(f"\n✅ Final merged CSV file(s) created. First file: {first_csv}")
    else:
        first_csv = final_csv
        print(f"\n✅ Final merged CSV created: {final_csv}")

    # Prompt user to open the merged CSV (mirror behavior from trc to csv.py)
    try:
        if messagebox.askyesno("Open merged CSV?", f"Do you want to open the first merged CSV file?\n{first_csv}"):
            if os.name == "nt":
                os.startfile(first_csv)
    except Exception:
        pass


def main(root):
    root.withdraw()
    print("📂 Please select one or more BUSMASTER .log or .txt files")
    log_files = list(filedialog.askopenfilenames(filetypes=[("Log/Text Files", "*.log;*.txt"), ("Log Files", "*.log"), ("Text Files", "*.txt")]))
    if not log_files:
        print("❌ No files selected.")
        return

    print(f"✅ Selected {len(log_files)} file(s)")

    # --- DBC selection ---
    print("\n📁 Please select the DBC source")
    dbc_source = select_dbc_file(root)
    if not dbc_source:
        print("❌ No DBC source selected.")
        return

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

    # --- Sampling time selection ---
    interval_var = tk.DoubleVar(value=0)
    interval_win = tk.Toplevel(root)
    interval_win.title("⏱️ Select Time Resolution")
    tk.Label(interval_win, text="Select the time resolution for the output CSV:", font=("Segoe UI", 12)).pack(pady=10)

    def set_interval(val):
        interval_var.set(val)
        interval_win.destroy()

    tk.Button(interval_win, text="Default timestamps (no resampling)", command=lambda: set_interval(0), width=30).pack(pady=5)
    tk.Button(interval_win, text="Resample every 300 ms", command=lambda: set_interval(0.3), width=30).pack(pady=5)
    tk.Button(interval_win, text="Resample every 500 ms", command=lambda: set_interval(0.5), width=30).pack(pady=5)
    tk.Button(interval_win, text="Resample every 1000 ms", command=lambda: set_interval(1), width=30).pack(pady=5)
    interval_win.grab_set()
    root.wait_window(interval_win)

    selected_interval = float(interval_var.get())

    # Parse and process
    parse_logs_to_csv_with_sampling(log_files, dbc, None, selected_interval)




if __name__ == "__main__":
    root = tk.Tk()
    main(root)
    # After main returns, destroy the hidden root so the script doesn't hang
    try:
        root.destroy()
    except Exception:
        pass
