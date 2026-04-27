import csv
import json
import re
import tempfile
import zipfile
from pathlib import Path
from functools import lru_cache
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False


HD_PATTERN = re.compile(r"(.+)_HD_(\d+)$")
EF_PATTERN = re.compile(r"_EF_(\d+)$")

CACHE_FILE = Path(tempfile.gettempdir()) / "holo_scanner_cache.json"


class Scanner:
    def __init__(self):
        self.results = []
        self.load_cache()

    def load_cache(self):
        if CACHE_FILE.exists():
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

    def scan_roots(self, roots, progress_callback=None):
        self.results.clear()

        self.find_best_hd_folder.cache_clear()
        self.find_best_ef_folder.cache_clear()
        self.find_h5_file.cache_clear()

        first_level_items = []

        for root in roots:
            root = Path(root)

            if root.exists():
                first_level_items.append(root)

                try:
                    for entry in root.iterdir():
                        if entry.is_dir():
                            first_level_items.append(entry)
                except Exception as e:
                    print(f"Error listing {root}: {e}")

        total = max(len(first_level_items), 1)

        for i, item in enumerate(first_level_items, start=1):
            if progress_callback:
                progress_callback(i, total, str(item))

            depth = 0 if item in map(Path, roots) else 1
            self._scan_limited_depth(item, depth=depth)

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


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Holo Scanner")
        self.root.geometry("1150x720")

        self.scanner = Scanner()
        self.folders = []
        self.filtered_results = []
        self.holo_or_patterns = []

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
        tk.Button(top, text="Export H5 ZIP", command=self.export_h5_zip).pack(side="left")
        tk.Button(top, text="Load regex TXT", command=self.load_regex_txt).pack(side="left")

        self.folder_list = tk.Listbox(self.root, height=4)
        self.folder_list.pack(fill="x", padx=5, pady=5)

        regex_frame = tk.Frame(self.root)
        regex_frame.pack(fill="x", padx=5, pady=3)

        self.regex_drop_label = tk.Label(
            regex_frame,
            text="Drop regex TXT here to filter HOLO paths with OR logic",
            relief="groove",
            height=2,
        )
        self.regex_drop_label.pack(fill="x")

        if HAS_DND:
            self.regex_drop_label.drop_target_register(DND_FILES)
            self.regex_drop_label.dnd_bind("<<Drop>>", self.on_regex_file_drop)

        filter_frame = tk.Frame(self.root)
        filter_frame.pack(fill="x", padx=5)

        for col in ("holo", "hd", "ef", "h5"):
            box = tk.Frame(filter_frame)
            box.pack(side="left", fill="x", expand=True, padx=2)

            tk.Label(box, text=f"{col.upper()} regex").pack(anchor="w")

            entry = tk.Entry(box, textvariable=self.filter_vars[col])
            entry.pack(fill="x")
            entry.bind("<KeyRelease>", lambda event: self.refresh_table())

        progress_frame = tk.Frame(self.root)
        progress_frame.pack(fill="x", padx=5, pady=5)

        self.progress = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", side="left", expand=True)

        self.progress_label = tk.Label(progress_frame, text="")
        self.progress_label.pack(side="left", padx=8)

        table_frame = tk.Frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=5, pady=5)

        columns = ("holo", "hd", "ef", "h5")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")

        for col in columns:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=270)

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

        self.progress["value"] = 0
        self.progress_label.config(text="Scanning...")

        def update_progress(i, total, current_path):
            self.progress["maximum"] = total
            self.progress["value"] = i
            self.progress_label.config(text=f"{i}/{total}")
            self.root.update_idletasks()

        self.scanner.scan_roots(self.folders, progress_callback=update_progress)

        self.progress_label.config(text="Done")
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

        if self.holo_or_patterns:
            matched = False

            for pattern in self.holo_or_patterns:
                try:
                    if re.search(pattern, row["holo"], flags=re.IGNORECASE):
                        matched = True
                        break
                except re.error:
                    continue

            if not matched:
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

    def load_regex_txt(self):
        file = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )

        if file:
            self.load_regex_patterns_from_file(file)

    def on_regex_file_drop(self, event):
        files = self.root.tk.splitlist(event.data)
        if files:
            self.load_regex_patterns_from_file(files[0])

    def load_regex_patterns_from_file(self, file):
        path = Path(file)

        if not path.exists():
            messagebox.showerror("Error", f"File does not exist:\n{path}")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                self.holo_or_patterns = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.strip().startswith("#")
                ]
        except Exception as e:
            messagebox.showerror("Error", f"Could not read regex file:\n{e}")
            return

        self.regex_drop_label.config(
            text=f"Loaded {len(self.holo_or_patterns)} HOLO regex patterns from {path.name}"
        )

        self.refresh_table()

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

        messagebox.showinfo("Success", "CSV and TXT export completed")

    def export_h5_zip(self):
        h5_paths = []

        for r in self.filtered_results:
            h5 = r.get("h5", "")
            if h5 and Path(h5).exists():
                h5_paths.append(Path(h5))

        if not h5_paths:
            messagebox.showwarning("Warning", "No H5 files to export")
            return

        zip_file = filedialog.asksaveasfilename(defaultextension=".zip")
        if not zip_file:
            return

        zip_path = Path(zip_file)

        try:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for i, h5_path in enumerate(h5_paths):
                    arcname = f"{i:05d}_{h5_path.name}"
                    z.write(h5_path, arcname=arcname)
        except Exception as e:
            messagebox.showerror("Error", f"Could not create ZIP:\n{e}")
            return

        messagebox.showinfo("Success", f"Exported {len(h5_paths)} H5 files to ZIP")


if __name__ == "__main__":
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    app = App(root)
    root.mainloop()