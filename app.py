from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk
from pathlib import Path

from reduction_tool.io import find_fits_files, group_by_filter, scan_project
from reduction_tool.models import FILTERS, ProjectPaths
from reduction_tool.plotting import save_rgb_image
from reduction_tool.processing import ALIGNMENT_AUTOMATIC, ALIGNMENT_NONE, run_reduction


class ReductionApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Astronomical Image Reduction Tool")
        self.configure_app_icon()
        self.geometry("820x560")
        self.minsize(760, 500)

        self.bias_dir = tk.StringVar()
        self.flat_dir = tk.StringVar()
        self.object_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.object_name = tk.StringVar(value="object")
        self.alignment_mode = tk.StringVar(value=ALIGNMENT_AUTOMATIC)
        self.status = tk.StringVar(value="Select the input and output folders to begin.")

        self._build_layout()
        self._bind_field_changes()
        self.update_generate_button_state()
        self.maximize_window()

    def maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            self.attributes("-zoomed", True)

    def configure_app_icon(self) -> None:
        assets_dir = Path(__file__).resolve().parent / "assets"
        icon_file = assets_dir / "airt-icon.ico"
        logo_file = assets_dir / "airt-logo.png"

        try:
            if icon_file.exists():
                self.iconbitmap(icon_file)
        except tk.TclError:
            pass

        try:
            if logo_file.exists():
                self.app_icon_image = tk.PhotoImage(file=logo_file)
                self.iconphoto(True, self.app_icon_image)
        except tk.TclError:
            pass

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

        ttk.Label(header, text="Alignment mode").grid(row=5, column=0, sticky="w", pady=(10, 0))
        alignment_options = {
            "Automatic band alignment": ALIGNMENT_AUTOMATIC,
            "No band adjustment": ALIGNMENT_NONE,
        }
        self.alignment_mode_labels = alignment_options
        self.alignment_mode_picker = ttk.Combobox(
            header,
            state="readonly",
            values=tuple(alignment_options.keys()),
        )
        self.alignment_mode_picker.grid(row=5, column=1, sticky="ew", padx=8, pady=(10, 0))
        self.alignment_mode_picker.set("Automatic band alignment")
        self.alignment_mode_picker.bind("<<ComboboxSelected>>", self.on_alignment_mode_selected)

        if hasattr(self, "app_icon_image"):
            self.header_logo_image = self.app_icon_image.subsample(6, 6)
            ttk.Label(header, image=self.header_logo_image).grid(
                row=0,
                column=3,
                rowspan=6,
                padx=(18, 0),
                sticky="ne",
            )

        actions = ttk.Frame(self, padding=(16, 0, 16, 12))
        actions.grid(row=1, column=0, sticky="ew")
        default_font = font.nametofont("TkDefaultFont")
        button_font = default_font.copy()
        button_font.configure(weight="bold")
        self.style = ttk.Style(self)
        self.style.configure("Primary.TButton", font=button_font, padding=(16, 8))
        self.generate_button = ttk.Button(
            actions,
            text="Generate RGB image",
            command=self.start_reduction,
            style="Primary.TButton",
            state="disabled",
        )
        self.generate_button.pack(side="left")

        body = ttk.Frame(self, padding=(16, 0, 16, 16))
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(body, columns=("bias", "flat", "object"), show="headings", height=8)
        self.tree.heading("bias", text="Bias")
        self.tree.heading("flat", text="Flats")
        self.tree.heading("object", text="Object")
        self.tree.column("bias", width=120, anchor="center")
        self.tree.column("flat", width=120, anchor="center")
        self.tree.column("object", width=120, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")

        log_frame = ttk.LabelFrame(body, text="Progress", padding=8)
        log_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        ttk.Label(log_frame, textvariable=self.status).grid(row=0, column=0, sticky="w")

        self._reset_table()

    def on_alignment_mode_selected(self, _event: object | None = None) -> None:
        selected = self.alignment_mode_picker.get()
        self.alignment_mode.set(self.alignment_mode_labels.get(selected, ALIGNMENT_AUTOMATIC))

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
            self.tree.insert("", "end", iid=band, values=(0, 0, 0), text=band)
        self.tree.configure(show="tree headings")
        self.tree.heading("#0", text="Filter")
        self.tree.column("#0", width=120, anchor="center")

    def choose_bias_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select the bias folder")
        if folder:
            self.bias_dir.set(folder)
            self.scan_files_partial()

    def choose_flat_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select the flat folder")
        if folder:
            self.flat_dir.set(folder)
            self.scan_files_partial()

    def choose_object_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select the object folder")
        if folder:
            self.object_dir.set(folder)
            self.object_name.set(Path(folder).name)
            if not self.output_dir.get().strip():
                self.output_dir.set(str(Path(folder).parent / "output"))
            self.scan_files_partial()

    def choose_output_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select the output folder")
        if folder:
            self.output_dir.set(folder)
            self.scan_files_partial()

    def _bind_field_changes(self) -> None:
        for variable in (
            self.bias_dir,
            self.flat_dir,
            self.object_dir,
            self.output_dir,
            self.object_name,
        ):
            variable.trace_add("write", self.on_field_changed)

    def on_field_changed(self, *_args: object) -> None:
        self.update_generate_button_state()

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

        bias_count = len(inventory.bias)
        for band, (flat_count, object_count) in inventory.counts_by_filter().items():
            self.tree.item(band, values=(bias_count, flat_count, object_count))

        self.status.set(
            f"Automatic scan complete: {bias_count} bias file(s). "
            "No images were processed yet."
        )

    def scan_files_partial(self) -> None:
        if self.bias_dir.get().strip() or self.flat_dir.get().strip() or self.object_dir.get().strip():
            bias_files = (
                find_fits_files(Path(self.bias_dir.get()))
                if self.bias_dir.get().strip()
                else []
            )
            flat_files = (
                find_fits_files(Path(self.flat_dir.get()))
                if self.flat_dir.get().strip()
                else []
            )
            object_files = (
                find_fits_files(Path(self.object_dir.get()))
                if self.object_dir.get().strip()
                else []
            )
            flats = group_by_filter(flat_files)
            objects = group_by_filter(object_files)
            bias_count = len(bias_files)

            for band in FILTERS:
                flat_count = len(flats.get(band, []))
                object_count = len(objects.get(band, []))
                self.tree.item(band, values=(bias_count, flat_count, object_count))

            self.status.set(
                "Automatic scan updated. "
                f"Bias: {bias_count}; "
                f"Flats: {len(flat_files)}; "
                f"Object: {len(object_files)}."
            )
        else:
            self._reset_table()
            self.status.set("Select folders to run the automatic scan.")

    def all_fields_ready(self) -> bool:
        return all(
            value.get().strip()
            for value in (
                self.bias_dir,
                self.flat_dir,
                self.object_dir,
                self.output_dir,
                self.object_name,
            )
        )

    def update_generate_button_state(self) -> None:
        state = "normal" if self.all_fields_ready() else "disabled"
        if hasattr(self, "generate_button"):
            self.generate_button.configure(state=state)

    def start_reduction(self) -> None:
        thread = threading.Thread(target=self.run_reduction, daemon=True)
        thread.start()

    def set_status(self, message: str) -> None:
        self.after(0, self.status.set, message)

    def show_info(self, title: str, message: str) -> None:
        self.after(0, messagebox.showinfo, title, message)

    def show_error(self, title: str, message: str) -> None:
        self.after(0, messagebox.showerror, title, message)

    def format_alignment_summary(self, result: object) -> str:
        if getattr(result, "alignment_mode", ALIGNMENT_NONE) == ALIGNMENT_NONE:
            return "Band alignment: none."

        reference = getattr(result, "alignment_reference", None) or "auto"
        channel_alignment = getattr(result, "channel_alignment", {})
        parts = []
        for band in ("R", "V", "B"):
            alignment = channel_alignment.get(band)
            if not alignment:
                continue
            if alignment.method in ("reference", "astroalign"):
                parts.append(f"{band}: {alignment.method}")
            else:
                parts.append(f"{band}: {alignment.method} dx={alignment.dx:.2f}, dy={alignment.dy:.2f}")
        detail = "; ".join(parts) if parts else "no channel shifts needed"
        return f"Band alignment: automatic, reference {reference}; {detail}."

    def run_reduction(self) -> None:
        try:
            object_name = self.object_name.get().strip() or "object"
            paths = self._project_paths()

            self.set_status("Processing bias, flats, alignment and RGB composition...")
            result = run_reduction(
                paths=paths,
                object_name=object_name,
                alignment_mode=self.alignment_mode.get(),
            )

            save_rgb_image(result.rgb, result.output_file)

            alignment_summary = self.format_alignment_summary(result)
            self.set_status(f"Image saved to: {result.output_file}. {alignment_summary}")
            self.show_info("Processing complete", f"Image saved to:\n{result.output_file}\n\n{alignment_summary}")
        except Exception as exc:
            self.set_status("Processing failed.")
            self.show_error("Processing error", str(exc))


if __name__ == "__main__":
    app = ReductionApp()
    app.mainloop()
