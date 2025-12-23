import csv
import os

OUTPUT_FILE = "merged.csv"


def merge_csv_files(csv_files, output_file=OUTPUT_FILE, open_after=False):
    """Merge multiple CSV files into a single CSV.

    - First CSV: header + all rows.
    - Subsequent CSVs: skip first 3 rows, append from 4th row onward
      (keeps behavior of the original standalone script).
    """
    csv_files = list(csv_files)
    if not csv_files:
        raise RuntimeError("No CSV files provided for merge")

    with open(output_file, "w", newline="", encoding="utf-8") as fout:
        writer = None

        for idx, file in enumerate(csv_files):
            with open(file, "r", encoding="utf-8") as fin:
                reader = csv.reader(fin)
                rows = list(reader)

                if not rows:
                    continue

                # First CSV → take header + all data
                if idx == 0:
                    header = rows[0]
                    writer = csv.writer(fout)
                    writer.writerow(header)

                    for row in rows[1:]:
                        if any(row):  # skip empty lines
                            writer.writerow(row)

                # Other CSVs → skip first 3 rows, take from 4th row onward
                else:
                    for row in rows[3:]:
                        if any(row):  # skip empty lines
                            writer.writerow(row)

    print(f"Merged {len(csv_files)} CSV files into {output_file}")

    if open_after:
        try:
            os.startfile(output_file)
        except Exception as e:
            print(f"Could not open file: {e}")


if __name__ == "__main__":
    # Tkinter is only needed for interactive use when running this file directly.
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()  # hide the main window
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
