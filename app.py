from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from reduction_tool.io import scan_project
from reduction_tool.models import FILTERS, ProjectPaths
from reduction_tool.plotting import save_rgb_image
from reduction_tool.processing import run_reduction


class ReductionApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Astronomical Image Reduction")
        self.geometry("820x560")
        self.minsize(760, 500)

        self.bias_dir = tk.StringVar()
        self.flat_dir = tk.StringVar()
        self.object_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.object_name = tk.StringVar(value="object")
        self.status = tk.StringVar(value="Select the input and output folders to begin.")

        self._build_layout()

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, padding=16)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        self._add_folder_picker(header, 0, "Bias folder", self.bias_dir, self.choose_bias_folder)
        self._add_folder_picker(header, 1, "Flat folder", self.flat_dir, self.choose_flat_folder)
        self._add_folder_picker(header, 2, "Object folder", self.object_dir, self.choose_object_folder)
        self._add_folder_picker(header, 3, "Output folder", self.output_dir, self.choose_output_folder)

        ttk.Label(header, text="Object name").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(header, textvariable=self.object_name).grid(row=4, column=1, sticky="ew", padx=8, pady=(10, 0))

        actions = ttk.Frame(self, padding=(16, 0, 16, 12))
        actions.grid(row=1, column=0, sticky="ew")
        ttk.Button(actions, text="Scan files only", command=self.scan_files).pack(side="left")
        ttk.Button(actions, text="Generate RGB image", command=self.start_reduction).pack(side="left", padx=8)

        body = ttk.Frame(self, padding=(16, 0, 16, 16))
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(body, columns=("flat", "object"), show="headings", height=8)
        self.tree.heading("flat", text="Flats")
        self.tree.heading("object", text="Object")
        self.tree.column("flat", width=120, anchor="center")
        self.tree.column("object", width=120, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")

        log_frame = ttk.LabelFrame(body, text="Progress", padding=8)
        log_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        ttk.Label(log_frame, textvariable=self.status).grid(row=0, column=0, sticky="w")

        self._reset_table()

    def _add_folder_picker(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command: callable,
    ) -> None:
        pady = (10, 0) if row else 0
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=pady)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8, pady=pady)
        ttk.Button(parent, text="Browse", command=command).grid(row=row, column=2, pady=pady)

    def _reset_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for band in FILTERS:
            self.tree.insert("", "end", iid=band, values=(0, 0), text=band)
        self.tree.configure(show="tree headings")
        self.tree.heading("#0", text="Filter")
        self.tree.column("#0", width=120, anchor="center")

    def choose_bias_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select the bias folder")
        if folder:
            self.bias_dir.set(folder)

    def choose_flat_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select the flat folder")
        if folder:
            self.flat_dir.set(folder)

    def choose_object_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select the object folder")
        if folder:
            self.object_dir.set(folder)
            self.object_name.set(Path(folder).name)
            if not self.output_dir.get().strip():
                self.output_dir.set(str(Path(folder).parent / "output"))

    def choose_output_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select the output folder")
        if folder:
            self.output_dir.set(folder)

    def _project_paths(self) -> ProjectPaths:
        missing = []
        if not self.bias_dir.get().strip():
            missing.append("bias folder")
        if not self.flat_dir.get().strip():
            missing.append("flat folder")
        if not self.object_dir.get().strip():
            missing.append("object folder")
        if not self.output_dir.get().strip():
            missing.append("output folder")

        if missing:
            raise ValueError(f"Select the required folder(s): {', '.join(missing)}.")

        return ProjectPaths.from_folders(
            bias_dir=Path(self.bias_dir.get()),
            flat_dir=Path(self.flat_dir.get()),
            object_dir=Path(self.object_dir.get()),
            output_dir=Path(self.output_dir.get()),
        )

    def scan_files(self) -> None:
        try:
            paths = self._project_paths()
            inventory = scan_project(paths)
        except Exception as exc:
            messagebox.showerror("File scan error", str(exc))
            return

        for band, (flat_count, object_count) in inventory.counts_by_filter().items():
            self.tree.item(band, values=(flat_count, object_count))

        self.status.set(
            f"Scan complete: {len(inventory.bias)} bias file(s). "
            "No images were processed yet."
        )

    def start_reduction(self) -> None:
        thread = threading.Thread(target=self.run_reduction, daemon=True)
        thread.start()

    def set_status(self, message: str) -> None:
        self.after(0, self.status.set, message)

    def show_info(self, title: str, message: str) -> None:
        self.after(0, messagebox.showinfo, title, message)

    def show_error(self, title: str, message: str) -> None:
        self.after(0, messagebox.showerror, title, message)

    def run_reduction(self) -> None:
        try:
            object_name = self.object_name.get().strip() or "object"
            paths = self._project_paths()

            self.set_status("Processing bias, flats, alignment and RGB composition...")
            result = run_reduction(paths=paths, object_name=object_name)

            caption = f"Processed in Python\nObject: {object_name}"
            save_rgb_image(result.rgb, result.output_file, f"RGB Image - {object_name}", caption)

            self.set_status(f"Image saved to: {result.output_file}")
            self.show_info("Processing complete", f"Image saved to:\n{result.output_file}")
        except Exception as exc:
            self.set_status("Processing failed.")
            self.show_error("Processing error", str(exc))


if __name__ == "__main__":
    app = ReductionApp()
    app.mainloop()
