import csv
import json
import re
import tempfile
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
# Temporary cache
# ----------------------------

CACHE_FILE = Path(tempfile.gettempdir()) / "holo_scanner_cache.json"


# ----------------------------
# File scanning logic
# ----------------------------

class Scanner:
    def __init__(self):
        self.results = []
        self.load_cache()

    def load_cache(self):
        if not CACHE_FILE.exists():
            return

        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                self.results = json.load(f)
        except Exception:
            self.results = []

    def save_cache(self):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.results, f, indent=2)
        except Exception as e:
            print(f"Could not save cache: {e}")

    def scan_roots(self, roots):
        self.results.clear()

        self.find_best_hd_folder.cache_clear()
        self.find_best_ef_folder.cache_clear()
        self.find_h5_file.cache_clear()

        for root in roots:
            self._scan_limited_depth(Path(root), depth=0)

        self.save_cache()

    def _scan_limited_depth(self, path, depth):
        if depth > 2:
            return

        try:
            for entry in path.iterdir():
                if entry.is_file() and entry.suffix.lower() == ".holo":
                    self.process_holo(entry)
                elif entry.is_dir():
                    self._scan_limited_depth(entry, depth + 1)
        except Exception as e:
            print(f"Error occurred while scanning {path}: {e}")

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
                if f.is_file() and f.suffix.lower() == ".h5":
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
        self.root.geometry("1100x650")

        self.scanner = Scanner()
        self.folders = []
        self.filtered_results = []

        self.filter_vars = {
            "holo": tk.StringVar(),
            "hd": tk.StringVar(),
            "ef": tk.StringVar(),
            "h5": tk.StringVar(),
        }

        self.setup_ui()
        self.refresh_table()

    def setup_ui(self):
        top = tk.Frame(self.root)
        top.pack(fill="x")

        tk.Button(top, text="Add Folder", command=self.add_folder).pack(side="left")
        tk.Button(top, text="Scan", command=self.scan).pack(side="left")
        tk.Button(top, text="Export CSV + TXT", command=self.export).pack(side="left")

        self.folder_list = tk.Listbox(self.root, height=4)
        self.folder_list.pack(fill="x", padx=5, pady=5)

        filter_frame = tk.Frame(self.root)
        filter_frame.pack(fill="x", padx=5)

        for col in ("holo", "hd", "ef", "h5"):
            box = tk.Frame(filter_frame)
            box.pack(side="left", fill="x", expand=True, padx=2)

            tk.Label(box, text=f"{col.upper()} regex").pack(anchor="w")

            entry = tk.Entry(box, textvariable=self.filter_vars[col])
            entry.pack(fill="x")
            entry.bind("<KeyRelease>", lambda event: self.refresh_table())

        table_frame = tk.Frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=5, pady=5)

        columns = ("holo", "hd", "ef", "h5")

        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")

        for col in columns:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=260)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
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

        self.scanner.scan_roots(self.folders)
        self.refresh_table()

    def row_matches_filters(self, row):
        for col, var in self.filter_vars.items():
            pattern = var.get().strip()
            if not pattern:
                continue

            try:
                if not re.search(pattern, row[col], flags=re.IGNORECASE):
                    return False
            except re.error:
                return False

        return True

    def refresh_table(self):
        self.tree.delete(*self.tree.get_children())

        self.filtered_results = [
            row for row in self.scanner.results
            if self.row_matches_filters(row)
        ]

        for r in self.filtered_results:
            self.tree.insert("", "end", values=(
                r["holo"],
                r["hd"],
                r["ef"],
                r["h5"],
            ))

    def export(self):
        if not self.filtered_results:
            messagebox.showwarning("Warning", "No data to export")
            return

        csv_file = filedialog.asksaveasfilename(defaultextension=".csv")
        if not csv_file:
            return

        csv_path = Path(csv_file)
        stem = csv_path.with_suffix("")

        txt_paths = {
            "holo": Path(f"{stem}_holo.txt"),
            "hd": Path(f"{stem}_hd.txt"),
            "ef": Path(f"{stem}_ef.txt"),
            "h5": Path(f"{stem}_h5.txt"),
        }

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["holo", "hd", "ef", "h5"])

            for r in self.filtered_results:
                writer.writerow([r["holo"], r["hd"], r["ef"], r["h5"]])

        for col, path in txt_paths.items():
            with open(path, "w", encoding="utf-8") as f:
                for r in self.filtered_results:
                    if r[col]:
                        f.write(r[col] + "\n")

        messagebox.showinfo(
            "Success",
            "Export completed:\n"
            f"{csv_path}\n"
            f"{txt_paths['holo']}\n"
            f"{txt_paths['hd']}\n"
            f"{txt_paths['ef']}\n"
            f"{txt_paths['h5']}"
        )


# ----------------------------
# Run app
# ----------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()