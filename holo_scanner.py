import csv
import json
import queue
import re
import tempfile
import threading
import time
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

COLUMNS = ("holo", "hd", "hd_version", "ef", "ef_version", "h5")

SUB_LEVEL_SCANNING = 2

EXCLUDED_STR = [
    "HD", # Do not look holo for files in HD folders
    "EF", # Do not look holo for files in EF folders
    # Example:
    # "backup",
    # "old",
    # "tmp",
]


class ProgressDialog:
    def __init__(self, parent):
        self.parent = parent
        self.window = tk.Toplevel(parent)
        self.window.title("Scanning")
        self.window.geometry("520x140")
        self.window.transient(parent)
        self.window.grab_set()

        self.label = tk.Label(self.window, text="Starting scan...")
        self.label.pack(fill="x", padx=12, pady=(12, 4))

        self.path_label = tk.Label(self.window, text="", anchor="w")
        self.path_label.pack(fill="x", padx=12)

        self.timer_label = tk.Label(self.window, text="Elapsed: 0.0 s", anchor="w")
        self.timer_label.pack(fill="x", padx=12)

        self.progress = ttk.Progressbar(self.window, mode="indeterminate")
        self.progress.pack(fill="x", padx=12, pady=12)

        self.window.update_idletasks()

    def set_indeterminate(self, text):
        self.label.config(text=text)
        self.progress.config(mode="indeterminate")
        self.progress.start(10)

    def set_determinate(self, text, maximum):
        self.progress.stop()
        self.label.config(text=text)
        self.progress.config(mode="determinate", maximum=max(maximum, 1), value=0)

    def update_found(self, count, path, elapsed):
        self.label.config(text=f"Finding .holo files... found {count}")
        self.path_label.config(text=path)
        self.timer_label.config(text=f"Elapsed: {elapsed:.1f} s")

    def update_processing(self, value, maximum, path, elapsed):
        self.progress["maximum"] = max(maximum, 1)
        self.progress["value"] = value
        self.label.config(text=f"Processing {value}/{maximum}")
        self.path_label.config(text=path)
        self.timer_label.config(text=f"Elapsed: {elapsed:.1f} s")

    def close(self):
        self.progress.stop()
        self.window.grab_release()
        self.window.destroy()


class Scanner:
    def __init__(self):
        self.results = []
        self.load_cache()

    def load_cache(self):
        if not CACHE_FILE.exists():
            return

        try:
            self.results = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            self.results = []

    def save_cache(self):
        try:
            CACHE_FILE.write_text(
                json.dumps(self.results, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"Could not save cache: {e}")

    def scan_roots(self, roots, progress_callback=None):
        self.results.clear()

        self.find_best_hd_folder.cache_clear()
        self.find_best_ef_folder.cache_clear()
        self.find_h5_file.cache_clear()
        self.read_version_txt.cache_clear()

        start_time = time.perf_counter()

        if progress_callback:
            progress_callback({
                "type": "finding_start",
                "elapsed": 0.0,
            })

        holo_files = []

        for root in roots:
            self._collect_holo_files(
                Path(root),
                depth=0,
                holo_files=holo_files,
                progress_callback=progress_callback,
                start_time=start_time,
            )

        if progress_callback:
            progress_callback({
                "type": "processing_start",
                "maximum": len(holo_files),
                "elapsed": time.perf_counter() - start_time,
            })

        for i, holo_path in enumerate(holo_files, start=1):
            self.process_holo(holo_path)

            if progress_callback:
                progress_callback({
                    "type": "processing",
                    "value": i,
                    "maximum": len(holo_files),
                    "path": str(holo_path),
                    "elapsed": time.perf_counter() - start_time,
                })

        self.save_cache()

        if progress_callback:
            progress_callback({
                "type": "done",
                "elapsed": time.perf_counter() - start_time,
            })

    def _collect_holo_files(
        self,
        path,
        depth,
        holo_files,
        progress_callback=None,
        start_time=None,
    ):
        if depth > SUB_LEVEL_SCANNING:
            return

        path_str = str(path).lower()

        for excluded in EXCLUDED_STR:
            if excluded.lower() in path_str:
                return

        try:
            for entry in path.iterdir():
                if entry.is_file() and entry.suffix.lower() == ".holo":
                    holo_files.append(entry)

                    if progress_callback:
                        progress_callback({
                            "type": "found_holo",
                            "count": len(holo_files),
                            "path": str(entry),
                            "elapsed": time.perf_counter() - start_time,
                        })

                elif entry.is_dir():
                    self._collect_holo_files(
                        entry,
                        depth + 1,
                        holo_files,
                        progress_callback=progress_callback,
                        start_time=start_time,
                    )

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
            "hd_version": self.read_version_txt(hd_folder) if hd_folder else "",
            "ef": str(ef_folder) if ef_folder else "",
            "ef_version": self.read_version_txt(ef_folder) if ef_folder else "",
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
        eyeflow = Path(hd_folder) / "eyeflow"

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
        h5_dir = Path(ef_folder) / "h5"

        if not h5_dir.exists():
            return None

        try:
            for f in h5_dir.iterdir():
                if f.is_file() and f.suffix.lower() == ".h5":
                    return f
        except PermissionError:
            pass

        return None

    @lru_cache(maxsize=None)
    def read_version_txt(self, folder):
        if not folder:
            return ""

        version_file = next(
            (
                p for p in Path(folder).glob("*version.txt")
                if not p.name.endswith("_git_version.txt")
            ),
            None,
        )

        if not version_file or not version_file.exists():
            return ""

        try:
            return version_file.read_text(
                encoding="utf-8",
                errors="replace",
            ).strip()
        except Exception:
            return ""

    def clear_cache(self):
        self.results.clear()

        if CACHE_FILE.exists():
            try:
                CACHE_FILE.unlink()
            except Exception as e:
                print(f"Could not delete cache: {e}")

        self.find_best_hd_folder.cache_clear()
        self.find_best_ef_folder.cache_clear()
        self.find_h5_file.cache_clear()
        self.read_version_txt.cache_clear()


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Holo Scanner")
        self.root.geometry("1300x760")

        self.scanner = Scanner()
        self.folders = []
        self.filtered_results = []
        self.holo_or_patterns = []

        self.scan_running = False
        self.scan_queue = None
        self.scan_progress = None

        self.filter_vars = {
            col: tk.StringVar()
            for col in COLUMNS
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
        tk.Button(top, text="Export PDF ZIP", command=self.export_pdf_zip).pack(side="left")
        tk.Button(top, text="Load regex TXT", command=self.load_regex_txt).pack(side="left")
        tk.Button(top, text="Clear regex TXT", command=self.clear_regex_txt).pack(side="left")
        tk.Button(top, text="Clear Cache", command=self.clear_cache).pack(side="left")

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

        for col in COLUMNS:
            box = tk.Frame(filter_frame)
            box.pack(side="left", fill="x", expand=True, padx=2)

            tk.Label(box, text=f"{col.upper()} regex").pack(anchor="w")

            entry = tk.Entry(box, textvariable=self.filter_vars[col])
            entry.pack(fill="x")
            entry.bind("<KeyRelease>", lambda event: self.refresh_table())

        status_frame = tk.Frame(self.root)
        status_frame.pack(fill="x", padx=5, pady=3)

        self.status_label = tk.Label(status_frame, text="")
        self.status_label.pack(anchor="w")

        table_frame = tk.Frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.tree = ttk.Treeview(table_frame, columns=COLUMNS, show="headings")

        for col in COLUMNS:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=210)

        scrollbar_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar_x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)

        self.tree.configure(
            yscrollcommand=scrollbar_y.set,
            xscrollcommand=scrollbar_x.set,
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")

        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

    def add_folder(self):
        folder = filedialog.askdirectory()

        if folder:
            self.folders.append(folder)
            self.folder_list.insert(tk.END, folder)

    def scan(self):
        if not self.folders:
            messagebox.showwarning("Warning", "No folders selected")
            return

        if self.scan_running:
            messagebox.showwarning("Warning", "Scan already running")
            return

        self.scan_running = True
        self.scan_queue = queue.Queue()
        self.scan_progress = ProgressDialog(self.root)

        def progress_callback(event):
            self.scan_queue.put(event)

        def worker():
            try:
                self.scanner.scan_roots(
                    self.folders,
                    progress_callback=progress_callback,
                )
            except Exception as e:
                self.scan_queue.put({
                    "type": "error",
                    "error": str(e),
                })

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        self.root.after(50, self.poll_scan_queue)

    def poll_scan_queue(self):
        finished = False
        error = None
        elapsed = 0.0

        while True:
            try:
                event = self.scan_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event.get("type")
            elapsed = event.get("elapsed", elapsed)

            if event_type == "finding_start":
                self.scan_progress.set_indeterminate("Finding .holo files...")

            elif event_type == "found_holo":
                self.scan_progress.update_found(
                    event.get("count", 0),
                    event.get("path", ""),
                    event.get("elapsed", 0.0),
                )

            elif event_type == "processing_start":
                self.scan_progress.set_determinate(
                    "Processing .holo files...",
                    event.get("maximum", 0),
                )

            elif event_type == "processing":
                self.scan_progress.update_processing(
                    event.get("value", 0),
                    event.get("maximum", 0),
                    event.get("path", ""),
                    event.get("elapsed", 0.0),
                )

            elif event_type == "done":
                finished = True
                elapsed = event.get("elapsed", 0.0)

            elif event_type == "error":
                finished = True
                error = event.get("error", "Unknown error")

        if finished:
            self.scan_running = False

            if self.scan_progress:
                self.scan_progress.close()
                self.scan_progress = None

            if error:
                messagebox.showerror("Error", f"Scan failed:\n{error}")
                return

            self.refresh_table()

            self.status_label.config(
                text=(
                    f"Scan completed in {elapsed:.2f} s. "
                    f"Showing {len(self.filtered_results)} / {len(self.scanner.results)} rows"
                )
            )

            messagebox.showinfo("Success", f"Scan completed in {elapsed:.2f} s")
            return

        self.root.after(50, self.poll_scan_queue)

    def row_matches_filters(self, row):
        for col, var in self.filter_vars.items():
            pattern = var.get().strip()

            if not pattern:
                continue

            try:
                if not re.search(pattern, row.get(col, ""), flags=re.IGNORECASE):
                    return False
            except re.error:
                return False

        if self.holo_or_patterns:
            for pattern in self.holo_or_patterns:
                try:
                    if re.search(pattern, row.get("holo", ""), flags=re.IGNORECASE):
                        return True
                except re.error:
                    continue

            return False

        return True

    def refresh_table(self):
        self.tree.delete(*self.tree.get_children())

        self.filtered_results = [
            row for row in self.scanner.results
            if self.row_matches_filters(row)
        ]

        for r in self.filtered_results:
            self.tree.insert(
                "",
                "end",
                values=tuple(r.get(col, "") for col in COLUMNS),
            )

        self.status_label.config(
            text=f"Showing {len(self.filtered_results)} / {len(self.scanner.results)} rows"
        )

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
            self.holo_or_patterns = [
                line.strip()
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        except Exception as e:
            messagebox.showerror("Error", f"Could not read regex file:\n{e}")
            return

        self.regex_drop_label.config(
            text=f"Loaded {len(self.holo_or_patterns)} HOLO regex patterns from {path.name}"
        )

        self.refresh_table()

    def clear_regex_txt(self):
        self.holo_or_patterns.clear()
        self.regex_drop_label.config(
            text="Drop regex TXT here to filter HOLO paths with OR logic"
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
            col: Path(f"{stem}_{col}.txt")
            for col in COLUMNS
        }

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS)

            for r in self.filtered_results:
                writer.writerow([r.get(col, "") for col in COLUMNS])

        for col, path in txt_paths.items():
            with open(path, "w", encoding="utf-8") as f:
                for r in self.filtered_results:
                    value = r.get(col, "")
                    if value:
                        f.write(value + "\n")

        messagebox.showinfo("Success", "CSV and TXT export completed")

    def export_h5_zip(self):
        self.export_zip_worker(
            kind="H5",
            extension=".h5",
            collect_paths=self.collect_h5_paths,
        )


    def export_pdf_zip(self):
        self.export_zip_worker(
            kind="PDF",
            extension=".pdf",
            collect_paths=self.collect_pdf_paths,
        )


    def collect_h5_paths(self):
        paths = []

        for r in self.filtered_results:
            h5 = r.get("h5", "")

            if h5 and Path(h5).exists():
                paths.append(Path(h5))

        return paths


    def collect_pdf_paths(self):
        paths = []

        for r in self.filtered_results:
            ef = r.get("ef", "")

            if not ef:
                continue

            pdf_dir = Path(ef) / "pdf"

            if not pdf_dir.exists():
                continue

            pdf_path = next(
                (p for p in pdf_dir.glob("*.pdf") if p.is_file()),
                None,
            )

            if pdf_path is not None:
                paths.append(pdf_path)

        return paths


    def export_zip_worker(self, kind, extension, collect_paths):
        if getattr(self, "export_running", False):
            messagebox.showwarning("Warning", "Export already running")
            return

        paths = collect_paths()

        if not paths:
            messagebox.showwarning("Warning", f"No {kind} files to export")
            return

        zip_file = filedialog.asksaveasfilename(
            defaultextension=".zip",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
        )

        if not zip_file:
            return

        self.export_running = True
        self.export_queue = queue.Queue()
        self.export_progress = ProgressDialog(self.root)

        zip_path = Path(zip_file)

        def worker():
            try:
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
                    used_names = set()
                    total = len(paths)

                    for i, path in enumerate(paths, start=1):
                        arcname = f"{i - 1:05d}_{path.name}"

                        duplicate_index = 1
                        while arcname in used_names:
                            arcname = (
                                f"{i - 1:05d}_{path.stem}_duplicate"
                                f"{duplicate_index}{path.suffix}"
                            )
                            duplicate_index += 1

                        used_names.add(arcname)
                        z.write(path, arcname=arcname)

                        self.export_queue.put({
                            "type": "progress",
                            "current": i,
                            "total": total,
                            "message": f"Exporting {kind} file {i}/{total}",
                        })

                self.export_queue.put({
                    "type": "done",
                    "count": len(paths),
                    "kind": kind,
                    "zip_path": str(zip_path),
                })

            except Exception as e:
                self.export_queue.put({
                    "type": "error",
                    "error": str(e),
                })

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        self.root.after(50, self.poll_export_queue)


    def poll_export_queue(self):
        try:
            while True:
                event = self.export_queue.get_nowait()

                if event["type"] == "progress":
                    current = event["current"]
                    total = event["total"]
                    message = event["message"]

                    if hasattr(self.export_progress, "label"):
                        self.export_progress.label.config(text=message)

                    if hasattr(self.export_progress, "progress"):
                        self.export_progress.progress["maximum"] = total
                        self.export_progress.progress["value"] = current

                elif event["type"] == "done":
                    self.export_running = False

                    if self.export_progress:
                        self.export_progress.window.destroy()
                        self.export_progress = None

                    messagebox.showinfo(
                        "Success",
                        f"Exported {event['count']} {event['kind']} files to ZIP",
                    )
                    return

                elif event["type"] == "error":
                    self.export_running = False

                    if self.export_progress:
                        self.export_progress.window.destroy()
                        self.export_progress = None

                    messagebox.showerror(
                        "Error",
                        f"Could not create ZIP:\n{event['error']}",
                    )
                    return

        except queue.Empty:
            pass

        if self.export_running:
            self.root.after(50, self.poll_export_queue)

    def clear_cache(self):
        if not messagebox.askyesno("Confirm", "Clear cache and results?"):
            return

        self.scanner.clear_cache()
        self.refresh_table()
        self.status_label.config(text="Cache cleared")

        for var in self.filter_vars.values():
            var.set("")

        self.holo_or_patterns.clear()
        self.regex_drop_label.config(
            text="Drop regex TXT here to filter HOLO paths with OR logic"
        )


def main():
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()