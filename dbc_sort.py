import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import cantools
import re

class DragListbox(tk.Listbox):

    def __init__(self, master, **kw):
        super().__init__(master, selectmode=tk.SINGLE, **kw)

        self.bind("<ButtonPress-1>", self.get_item)
        self.bind("<B1-Motion>", self.shift_item)

    def get_item(self, event):
        self.curIndex = self.nearest(event.y)

    def shift_item(self, event):

        i = self.nearest(event.y)

        if i < self.curIndex:
            x = self.get(i)
            self.delete(i)
            self.insert(i+1, x)
            self.curIndex = i

        elif i > self.curIndex:
            x = self.get(i)
            self.delete(i)
            self.insert(i-1, x)
            self.curIndex = i

class DBCEditor:
    def __init__(self, root):

        self.root = root
        self.root.title("DBC CSV_ORDER Editor")
        self.root.geometry("900x560")
        self.dbc = None
        self.dbc_text = ""
        self.signal_msg = {}
        self.all_signals = []

        tk.Button(root, text="Load DBC", command=self.load_dbc, height=2).pack(pady=10)
        frame = tk.Frame(root)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="Signals").grid(row=0, column=0)
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self.filter_signals)
        self.search_box = tk.Entry(frame, textvariable=self.search_var, width=40)
        self.search_box.grid(row=1, column=0, padx=10, pady=5)
        self.left = tk.Listbox(frame, width=40, height=20)
        self.left.grid(row=2, column=0, padx=10)
        btns = tk.Frame(frame)
        btns.grid(row=2, column=1)
        tk.Button(btns, text=">>", command=self.move_right).pack(pady=10)
        tk.Button(btns, text="<<", command=self.move_left).pack(pady=10)
        tk.Button(btns, text="Special Edit", command=self.special_edit).pack(pady=10)
        tk.Label(frame, text="Priority Order").grid(row=0, column=2)
        self.right = DragListbox(frame, width=40, height=22)
        self.right.grid(row=2, column=2, padx=10)
        tk.Button(root, text="Save DBC", command=self.save_dbc, height=2).pack(pady=10)
    # --------------------------------------
    def extract_existing_csv_order(self):
        pattern = r'BA_\s+"CSV_ORDER"\s+SG_\s+(\d+)\s+(\S+)\s+(\d+);'
        orders = {}
        for msg, sig, rank in re.findall(pattern, self.dbc_text):
            orders[sig] = int(rank)
        return orders
    # --------------------------------------
    def load_dbc(self):
        path = filedialog.askopenfilename(filetypes=[("DBC files","*.dbc")])
        if not path:
            return

        with open(path,"r",encoding="utf8") as f:
            self.dbc_text = f.read()

        self.dbc = cantools.database.load_file(path)

        self.left.delete(0,tk.END)
        self.right.delete(0,tk.END)

        existing = self.extract_existing_csv_order()

        signals = []

        for msg in self.dbc.messages:
            for sig in msg.signals:

                signals.append(sig.name)
                self.signal_msg[sig.name] = msg.frame_id

        signals = sorted(set(signals))
        self.all_signals = signals

        ordered = []
        remaining = []

        for s in signals:
            if s in existing:
                ordered.append((existing[s], s))
            else:
                remaining.append(s)

        ordered.sort()
        for _, s in ordered:
            self.right.insert(tk.END, s)
        for s in remaining:
            self.left.insert(tk.END, s)
    # --------------------------------------
    def filter_signals(self, *args):

        search = self.search_var.get().lower()

        self.left.delete(0, tk.END)

        for sig in self.all_signals:

            if search in sig.lower() and sig not in self.right.get(0, tk.END):
                self.left.insert(tk.END, sig)
    # --------------------------------------
    def move_right(self):
        sel = self.left.curselection()
        if not sel:
            return
        val = self.left.get(sel)
        self.left.delete(sel)
        self.right.insert(tk.END,val)
    # --------------------------------------
    def move_left(self):
        sel = self.right.curselection()
        if not sel:
            return
        val = self.right.get(sel)
        self.right.delete(sel)
        self.left.insert(tk.END,val)
    # --------------------------------------
    def special_edit(self):
        sel = self.right.curselection()
        if not sel:
            messagebox.showwarning("Select signal","Select signal to move")
            return
        signal = self.right.get(sel)
        target = simpledialog.askstring(
            "Insert After",
            f"Insert '{signal}' after which signal?"
        )

        if not target:
            return
        signals = list(self.right.get(0, tk.END))
        if target not in signals:
            messagebox.showerror("Error","Target signal not found in priority list")
            return
        signals.remove(signal)
        index = signals.index(target) + 1
        signals.insert(index, signal)
        self.right.delete(0, tk.END)
        for s in signals:
            self.right.insert(tk.END, s)
    # --------------------------------------
    def ensure_definition(self):

        if 'BA_DEF_ SG_ "CSV_ORDER"' in self.dbc_text:
            return
        definition = (
            '\nBA_DEF_ SG_ "CSV_ORDER" INT 0 10000;\n'
            'BA_DEF_DEF_ "CSV_ORDER" 0;\n'
        )
        lines = self.dbc_text.splitlines()
        for i,l in enumerate(lines):
            if l.startswith("VERSION"):
                lines.insert(i+1,definition)
                break
        self.dbc_text = "\n".join(lines)

    # --------------------------------------

    def remove_old_csv_orders(self):
        pattern = r'BA_\s+"CSV_ORDER"\s+SG_\s+\d+\s+\S+\s+\d+;\n?'
        self.dbc_text = re.sub(pattern, '', self.dbc_text)

    # --------------------------------------

    def save_dbc(self):
        if not self.dbc:
            return
        ordered = list(self.right.get(0,tk.END))
        if not ordered:
            messagebox.showwarning("No signals","Please select signals")
            return
        self.ensure_definition()
        self.remove_old_csv_orders()
        csv_lines = []
        for i,sig in enumerate(ordered,1):
            msg_id = self.signal_msg.get(sig)
            if msg_id is None:
                continue
            csv_lines.append(f'BA_ "CSV_ORDER" SG_ {msg_id} {sig} {i};')
        final_text = self.dbc_text.rstrip() + "\n\n" + "\n".join(csv_lines) + "\n"
        save = filedialog.asksaveasfilename(defaultextension=".dbc")

        if not save:
            return
        with open(save,"w",encoding="utf8") as f:
            f.write(final_text)
        messagebox.showinfo("Done","DBC saved.")

root = tk.Tk()
DBCEditor(root)
root.mainloop()
