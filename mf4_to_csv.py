import os
import pandas as pd
import cantools
from asammdf import MDF
import tkinter as tk
from tkinter import filedialog


def select_file(root, title, filetypes):
    """Use existing Tk root instead of creating a new one."""
    return filedialog.askopenfilename(
        parent=root,
        title=title,
        filetypes=filetypes
    )


def main(root):
    print("Select MDF (.mf4) file")
    mdf_file = select_file(
        root,
        "Select MDF file",
        [("MDF files", "*.mf4 *.mdf")]
    )
    if not mdf_file:
        print("No MDF selected")
        return

    print("Select DBC file")
    dbc_file = select_file(
        root,
        "Select DBC file",
        [("DBC files", "*.dbc")]
    )
    if not dbc_file:
        print("No DBC selected")
        return

    print("Loading DBC...")
    db = cantools.database.load_file(dbc_file)

    print("Reading MDF...")
    mdf = MDF(mdf_file)

    records = []

    # Iterate through all MDF groups
    for group_index, group in enumerate(mdf.groups):
        try:
            timestamps = mdf.get("Timestamp", group=group_index).samples
            ids = mdf.get("CAN_DataFrame.ID", group=group_index).samples
            data_bytes = mdf.get("CAN_DataFrame.DataBytes", group=group_index).samples
        except Exception:
            continue  # Skip non-CAN groups

        print(f"Processing group {group_index}...")

        for ts, frame_id, data in zip(timestamps, ids, data_bytes):
            try:
                frame_id = int(frame_id)
                raw_bytes = bytes(data)

                decoded = db.decode_message(
                    frame_id,
                    raw_bytes,
                    decode_choices=True
                )

                row = {
                    "Timestamp": float(ts),
                    "CAN_ID": hex(frame_id)
                }

                row.update(decoded)
                records.append(row)

            except Exception:
                continue  # Skip frames not present in DBC

    if not records:
        print("⚠ No frames decoded. DBC may not match log.")
        return

    print("Building DataFrame...")
    df = pd.DataFrame(records)

    # Sort by timestamp
    df = df.sort_values("Timestamp").reset_index(drop=True)

    # Forward fill (Last value hold)
    print("Applying last-value hold (forward fill)...")
    signal_columns = [
        col for col in df.columns
        if col not in ["Timestamp", "CAN_ID"]
    ]
    df[signal_columns] = df[signal_columns].ffill()

    output_file = os.path.splitext(mdf_file)[0] + "_decoded_latched.csv"
    df.to_csv(output_file, index=False)

    print("\n✅ CSV created successfully:")
    print(output_file)


# Allow standalone execution
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    main(root)
