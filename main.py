import os
import re
import csv
from pathlib import Path
from functools import lru_cache
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

# ----------------------------
# Regex patterns
# ----------------------------
HD_PATTERN = re.compile(r"(.+)_HD_(\d+)$")
EF_PATTERN = re.compile(r"_EF_(\d+)$")


# ----------------------------
# File scanning logic (cached)
# ----------------------------

class Scanner:
    def __init__(self):
        self.results = []

    def scan_roots(self, roots):
        self.results.clear()
        for root in roots:
            self._scan_limited_depth(Path(root), depth=0)

    def _scan_limited_depth(self, path, depth):
        if depth > 2:
            return

        try:
            for entry in path.iterdir():
                if entry.is_file() and entry.suffix == ".holo":
                    self.process_holo(entry)
                elif entry.is_dir():
                    self._scan_limited_depth(entry, depth + 1)
        except PermissionError:
            pass

    def process_holo(self, holo_path):
        base_name = holo_path.stem
        parent = holo_path.parent

        hd_folder = self.find_best_hd_folder(parent, base_name)

        ef_folder = None
        h5_file = None

        if hd_folder:
            ef_folder = self.find_best_ef_folder(hd_folder)
            if ef_folder:
                h5_file = self.find_h5_file(ef_folder)

        self.results.append({
            "holo": str(holo_path),
            "hd": str(hd_folder) if hd_folder else "",
            "ef": str(ef_folder) if ef_folder else "",
            "h5": str(h5_file) if h5_file else "",
        })

    @lru_cache(maxsize=None)
    def find_best_hd_folder(self, parent, base_name):
        best = None
        best_num = -1

        try:
            for d in parent.iterdir():
                if not d.is_dir():
                    continue

                match = HD_PATTERN.match(d.name)
                if match and match.group(1) == base_name:
                    num = int(match.group(2))
                    if num > best_num:
                        best_num = num
                        best = d
        except PermissionError:
            pass

        return best

    @lru_cache(maxsize=None)
    def find_best_ef_folder(self, hd_folder):
        eyeflow = hd_folder / "eyeflow"
        if not eyeflow.exists():
            return None

        best = None
        best_num = -1

        try:
            for d in eyeflow.iterdir():
                if not d.is_dir():
                    continue

                match = EF_PATTERN.search(d.name)
                if match:
                    num = int(match.group(1))
                    if num > best_num:
                        best_num = num
                        best = d
        except PermissionError:
            pass

        return best

    @lru_cache(maxsize=None)
    def find_h5_file(self, ef_folder):
        h5_dir = ef_folder / "h5"
        if not h5_dir.exists():
            return None

        try:
            for f in h5_dir.iterdir():
                if f.suffix == ".h5":
                    return f
        except PermissionError:
            pass

        return None


# ----------------------------
# GUI
# ----------------------------

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Holo Scanner")
        self.root.geometry("900x600")

        self.scanner = Scanner()
        self.folders = []

        self.setup_ui()

    def setup_ui(self):
        frame = tk.Frame(self.root)
        frame.pack(fill="x")

        tk.Button(frame, text="Add Folder", command=self.add_folder).pack(side="left")
        tk.Button(frame, text="Scan", command=self.scan).pack(side="left")
        tk.Button(frame, text="Export CSV", command=self.export).pack(side="left")

        self.folder_list = tk.Listbox(self.root, height=4)
        self.folder_list.pack(fill="x", padx=5, pady=5)

        # Table
        columns = ("holo", "hd", "ef", "h5")

        self.tree = ttk.Treeview(self.root, columns=columns, show="headings")

        for col in columns:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=200)

        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folders.append(folder)
            self.folder_list.insert(tk.END, folder)

    def scan(self):
        if not self.folders:
            messagebox.showwarning("Warning", "No folders selected")
            return

        self.tree.delete(*self.tree.get_children())

        self.scanner.scan_roots(self.folders)

        for r in self.scanner.results:
            self.tree.insert("", "end", values=(
                r["holo"],
                r["hd"],
                r["ef"],
                r["h5"]
            ))

    def export(self):
        if not self.scanner.results:
            messagebox.showwarning("Warning", "No data to export")
            return

        file = filedialog.asksaveasfilename(defaultextension=".csv")
        if not file:
            return

        with open(file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["holo", "hd", "ef", "h5"])

            for r in self.scanner.results:
                writer.writerow([r["holo"], r["hd"], r["ef"], r["h5"]])

        messagebox.showinfo("Success", "Export completed")


# ----------------------------
# Run app
# ----------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()