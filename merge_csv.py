import os
import math
from typing import Iterable, List
import pandas as pd

OUTPUT_FILE = "merged.csv"

def _detect_and_strip_unit_row(df: pd.DataFrame):
    """Detect unit row and remove it."""

    if df.empty:
        return {}, df

    first_row = df.iloc[0]
    is_unit_row = False

    time_col = None
    if "Time (s)" in df.columns:
        time_col = "Time (s)"
    elif "Time" in df.columns:
        time_col = "Time"

    if time_col is not None:
        try:
            float(str(first_row[time_col]))
        except (TypeError, ValueError):
            is_unit_row = True

    units = {}

    if is_unit_row:
        for col in df.columns:
            val = first_row[col]
            if pd.notna(val) and str(val).strip() != "":
                units[col] = str(val)

        df = df.iloc[1:].reset_index(drop=True)

    return units, df


def merge_csv_files(
    csv_files: Iterable[str],
    output_file: str = OUTPUT_FILE,
    open_after: bool = False,
    row_limit: int | None = None,
):

    csv_list: List[str] = list(csv_files)

    if not csv_list:
        raise RuntimeError("No CSV files provided for merge")

    dataframes: List[pd.DataFrame] = []
    all_units = {}

    for path in csv_list:

        if not os.path.exists(path):
            print(f"Warning: CSV file not found, skipping: {path}")
            continue

        df = pd.read_csv(path, dtype=str)

        if df.empty:
            continue

        units, df_no_units = _detect_and_strip_unit_row(df)

        # -----------------------------
        # REMOVE FIRST 25 ROWS FROM EACH CSV
        # -----------------------------
        if len(df_no_units) > 25:
            df_no_units = df_no_units.iloc[25:].reset_index(drop=True)
        else:
            df_no_units = df_no_units.iloc[0:0]

        all_units.update({k: v for k, v in units.items() if v is not None})
        dataframes.append(df_no_units)

    if not dataframes:
        raise RuntimeError("No non-empty CSV data to merge")

    # -----------------------------
    # Build column union
    # -----------------------------

    all_columns = []
    seen = set()

    for df in dataframes:
        for col in df.columns:
            if col not in seen:
                seen.add(col)
                all_columns.append(col)

    # Remove Time(s) if DATE + TIME exist
    if "DATE" in seen and "TIME" in seen:
        all_columns = [c for c in all_columns if c != "Time (s)"]

    elif "Time (s)" in seen:
        all_columns = ["Time (s)"] + [c for c in all_columns if c != "Time (s)"]

    elif "Time" in seen:
        all_columns = ["Time"] + [c for c in all_columns if c != "Time"]

    normalized = [df.reindex(columns=all_columns) for df in dataframes]

    merged_df = pd.concat(normalized, ignore_index=True)

    # -----------------------------
    # Add unit row
    # -----------------------------

    if all_units:
        unit_row = [all_units.get(col, "") for col in all_columns]
        units_df = pd.DataFrame([unit_row], columns=all_columns)
        final_df = pd.concat([units_df, merged_df], ignore_index=True)

    else:
        final_df = merged_df

    # -----------------------------
    # Remove completely empty rows
    # -----------------------------

    tmp = final_df.replace(r"^\s*$", pd.NA, regex=True)
    final_df = tmp.dropna(how="all").reset_index(drop=True)

    # -----------------------------
    # Remove columns with no data
    # -----------------------------

    if len(final_df) > 1:
        data_only = final_df.iloc[1:]
        tmp_cols = data_only.replace(r"^\s*$", pd.NA, regex=True)
        cols_to_keep = ~tmp_cols.isna().all(axis=0)

        if "DATE" in final_df.columns:
            cols_to_keep["DATE"] = True

        if "TIME" in final_df.columns:
            cols_to_keep["TIME"] = True

        if "Time (s)" in final_df.columns:
            cols_to_keep["Time (s)"] = True

        final_df = final_df.loc[:, cols_to_keep]

    # -----------------------------
    # Split large files
    # -----------------------------

    if row_limit is not None and row_limit > 0:

        total_rows = len(final_df)
        total_parts = math.ceil(total_rows / row_limit)
        base, ext = os.path.splitext(output_file)
        output_paths: List[str] = []

        print(
            f"Writing merged data to CSV in {total_parts} part(s) "
            f"(max {row_limit} rows per file)..."
        )

        for i in range(total_parts):

            start = i * row_limit
            end = (i + 1) * row_limit
            chunk = final_df.iloc[start:end]
            suffix = "" if i == 0 else f"_part{i+1}"
            path = f"{base}{suffix}{ext}"
            chunk.to_csv(path, index=False)
            output_paths.append(path)
            print(f"✔ Saved: {path} ({len(chunk)} rows)")

        if open_after and output_paths:
            try:
                os.startfile(output_paths[0])
            except Exception as e:
                print(f"Could not open file: {e}")

        print(f"Merged {len(csv_list)} CSV files into {len(output_paths)} output file(s).")
        return output_paths

    # -----------------------------
    # Write single CSV
    # -----------------------------

    final_df.to_csv(output_file, index=False)

    print(f"Merged {len(csv_list)} CSV files into {output_file}")

    if open_after:
        try:
            os.startfile(output_file)
        except Exception as e:
            print(f"Could not open file: {e}")


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
