import os
import csv
import math
from typing import Iterable, List

OUTPUT_FILE = "merged.csv"

def _read_header(path: str):
    """Return (units_dict, data_columns, has_unit_row) without reading the whole file."""
    with open(path, newline='', encoding='utf-8', errors='ignore') as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return {}, [], False

        try:
            second = next(reader)
        except StopIteration:
            return {}, header, False

    # Detect unit row: Time (s) column should be numeric in a data row
    time_idx = None
    for i, col in enumerate(header):
        if col in ("Time (s)", "Time"):
            time_idx = i
            break

    is_unit_row = False
    if time_idx is not None:
        try:
            float(second[time_idx])
        except (ValueError, IndexError):
            is_unit_row = True

    units = {}
    if is_unit_row:
        for col, val in zip(header, second):
            v = val.strip()
            if v:
                units[col] = v

    return units, header, is_unit_row


def _iter_data_rows(path: str, has_unit_row: bool, skip_first_n: int = 25):
    """
    Yield data rows (as lists) from a CSV, skipping header and optional unit row.
    Also skips the first `skip_first_n` data rows (matches original behaviour).
    """
    with open(path, newline='', encoding='utf-8', errors='ignore') as fh:
        reader = csv.reader(fh)
        next(reader, None)              # skip header
        if has_unit_row:
            next(reader, None)          # skip unit row

        skipped = 0
        for row in reader:
            if skipped < skip_first_n:
                skipped += 1
                continue
            yield row


def merge_csv_files(
    csv_files: Iterable[str],
    output_file: str = OUTPUT_FILE,
    open_after: bool = False,
    row_limit: int | None = None,
):
    csv_list: List[str] = [f for f in csv_files if os.path.exists(f)]

    if not csv_list:
        raise RuntimeError("No valid CSV files provided for merge")

    # ---- Pass 1: collect headers, units, column union ----
    print("📋 Reading headers...")
    file_meta = []   # list of (path, units_dict, columns, has_unit_row)
    all_columns: List[str] = []
    seen_cols: set = set()
    all_units: dict = {}

    for path in csv_list:
        units, columns, has_unit_row = _read_header(path)
        file_meta.append((path, units, columns, has_unit_row))
        all_units.update({k: v for k, v in units.items() if v})
        for col in columns:
            if col not in seen_cols:
                seen_cols.add(col)
                all_columns.append(col)

    if not all_columns:
        raise RuntimeError("No columns found in any CSV file")

    # Decide time column ordering
    has_date = "DATE" in seen_cols
    has_time_col = "TIME" in seen_cols
    has_time_s = "Time (s)" in seen_cols
    has_time = "Time" in seen_cols

    if has_date and has_time_col:
        # Remove Time (s) from output
        all_columns = [c for c in all_columns if c != "Time (s)"]
    elif has_time_s:
        all_columns = ["Time (s)"] + [c for c in all_columns if c != "Time (s)"]
    elif has_time:
        all_columns = ["Time"] + [c for c in all_columns if c != "Time"]

    num_cols = len(all_columns)
    col_index = {c: i for i, c in enumerate(all_columns)}
    EMPTY = ""

    # ---- Pass 2: stream all rows into a single temp file ----
    tmp_path = output_file + ".tmp_merge"
    print("🔀 Streaming rows into merged file...")
    total_rows_written = 0

    # Track which columns have at least one non-empty value (for cleanup)
    col_has_data = [False] * num_cols
    # Always keep these
    for always_keep in ("DATE", "TIME", "Time (s)", "Time"):
        if always_keep in col_index:
            col_has_data[col_index[always_keep]] = True

    with open(tmp_path, 'w', newline='', encoding='utf-8') as out_fh:
        writer = csv.writer(out_fh)
        writer.writerow(all_columns)    # header only — units injected later

        for path, units, src_columns, has_unit_row in file_meta:
            src_idx = [col_index.get(c) for c in src_columns]   # position in all_columns

            for src_row in _iter_data_rows(path, has_unit_row, skip_first_n=25):

                # Skip completely empty rows
                if not any(v.strip() for v in src_row):
                    continue

                out_row = [EMPTY] * num_cols
                for s_i, dest_i in enumerate(src_idx):
                    if dest_i is None:
                        continue
                    val = src_row[s_i] if s_i < len(src_row) else EMPTY
                    out_row[dest_i] = val
                    if val.strip():
                        col_has_data[dest_i] = True

                writer.writerow(out_row)
                total_rows_written += 1

    print(f"   {total_rows_written:,} data rows merged")

    # ---- Determine columns to keep ----
    keep_indices = [i for i, has in enumerate(col_has_data) if has]
    final_columns = [all_columns[i] for i in keep_indices]

    # ---- Pass 3: read temp, inject units row, write final output(s) ----
    unit_row = [all_units.get(c, "") for c in final_columns]

    if row_limit and row_limit > 0:
        # Split into multiple output files
        base, ext = os.path.splitext(output_file)
        output_paths: List[str] = []
        part = 0
        row_in_part = 0
        out_fh = None
        writer = None

        def _open_next_part():
            nonlocal out_fh, writer, part, row_in_part
            if out_fh:
                out_fh.close()
            part += 1
            suffix = "" if part == 1 else f"_part{part}"
            path = f"{base}{suffix}{ext}"
            output_paths.append(path)
            out_fh = open(path, 'w', newline='', encoding='utf-8')
            writer = csv.writer(out_fh)
            writer.writerow(final_columns)
            if all_units:
                writer.writerow(unit_row)
                row_in_part = 1
            else:
                row_in_part = 0
            print(f"📄 Writing part: {path}")

        _open_next_part()

        with open(tmp_path, newline='', encoding='utf-8') as tmp_fh:
            reader = csv.reader(tmp_fh)
            next(reader, None)   # skip header

            for src_row in reader:
                out_row = [src_row[i] if i < len(src_row) else EMPTY for i in keep_indices]
                writer.writerow(out_row)
                row_in_part += 1

                if row_in_part >= row_limit:
                    _open_next_part()

        if out_fh:
            out_fh.close()

        os.remove(tmp_path)
        print(f"✔ Merged {len(csv_list)} CSV file(s) → {len(output_paths)} output file(s)")

        if open_after and output_paths:
            try:
                os.startfile(output_paths[0])
            except Exception as e:
                print(f"Could not open file: {e}")

        return output_paths

    else:
        # Single output file
        with open(output_file, 'w', newline='', encoding='utf-8') as out_fh:
            writer = csv.writer(out_fh)
            writer.writerow(final_columns)
            if all_units:
                writer.writerow(unit_row)

            with open(tmp_path, newline='', encoding='utf-8') as tmp_fh:
                reader = csv.reader(tmp_fh)
                next(reader, None)   # skip header
                for src_row in reader:
                    out_row = [src_row[i] if i < len(src_row) else EMPTY for i in keep_indices]
                    writer.writerow(out_row)

        os.remove(tmp_path)
        print(f"✔ Merged {len(csv_list)} CSV file(s) → {output_file}")

        if open_after:
            try:
                os.startfile(output_file)
            except Exception as e:
                print(f"Could not open file: {e}")

        return [output_file]


# ------------------ STANDALONE USE ------------------
if __name__ == "__main__":
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.update()

    csv_files = filedialog.askopenfilenames(
        title="Select CSV files to merge",
        filetypes=[("CSV files", "*.csv")]
    )
    root.destroy()

    csv_files = list(csv_files)
    if not csv_files:
        raise RuntimeError("No CSV files selected")

    merge_csv_files(csv_files, OUTPUT_FILE, open_after=True)
