from __future__ import annotations

import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

import matplotlib.pyplot as plt
from PIL import Image, ImageTk

from reduction_tool.io import find_fits_files, group_by_filter, scan_project
from reduction_tool.models import FILTERS, ProjectPaths
from reduction_tool.plotting import save_rgb_image
from reduction_tool.processing import (
    ALIGNMENT_AUTOMATIC,
    ALIGNMENT_MANUAL,
    ALIGNMENT_NONE,
    apply_channel_offsets,
    create_available_channel_rgb,
    run_reduction,
)

DARK_BG = "#0b1020"
PANEL_BG = "#0f172a"
FIELD_BG = "#111827"
BORDER = "#24304a"
TEXT = "#e5ecff"
MUTED_TEXT = "#9aa7c7"
ACCENT = "#4f8cff"
ACCENT_HOVER = "#6d5dfc"
HEADER_ICON_SIZE = 150


class ManualAlignmentWindow(tk.Toplevel):
    def __init__(self, parent: "ReductionApp", result: object) -> None:
        super().__init__(parent)
        self.parent = parent
        self.result = result
        self.title("Manual band alignment")
        self.geometry("980x760")
        self.minsize(860, 620)
        self.configure_app_icon()
        self.configure(bg=DARK_BG)

        self.available_bands = [band for band in ("R", "V", "B") if band in result.stacked]
        self.offsets = {band: [0.0, 0.0] for band in self.available_bands}
        self.selected_band = tk.StringVar(value=self.available_bands[0] if self.available_bands else "")
        self.step = tk.DoubleVar(value=1.0)
        self.dx = tk.DoubleVar(value=0.0)
        self.dy = tk.DoubleVar(value=0.0)
        self.status = tk.StringVar(value="Adjust a channel and update the preview.")
        self.preview_tempdir = tempfile.TemporaryDirectory()
        self.preview_file = Path(self.preview_tempdir.name) / "manual_alignment_preview.png"
        self.preview_image: tk.PhotoImage | None = None

        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Left>", lambda _event: self.nudge(-self.step.get(), 0.0))
        self.bind("<Right>", lambda _event: self.nudge(self.step.get(), 0.0))
        self.bind("<Up>", lambda _event: self.nudge(0.0, self.step.get()))
        self.bind("<Down>", lambda _event: self.nudge(0.0, -self.step.get()))
        self.bind("<Shift-Left>", lambda _event: self.nudge(-10.0, 0.0))
        self.bind("<Shift-Right>", lambda _event: self.nudge(10.0, 0.0))
        self.bind("<Shift-Up>", lambda _event: self.nudge(0.0, 10.0))
        self.bind("<Shift-Down>", lambda _event: self.nudge(0.0, -10.0))
        self.render_preview()
        self.focus_set()
        self.grab_set()

    def configure_app_icon(self) -> None:
        try:
            if hasattr(self.parent, "app_icon_image"):
                self.iconphoto(True, self.parent.app_icon_image)
        except tk.TclError:
            pass

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        preview_frame = ttk.Frame(self, padding=12, style="Panel.TFrame")
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.preview_label = ttk.Label(preview_frame, anchor="center", style="Preview.TLabel")
        self.preview_label.grid(row=0, column=0, sticky="nsew")

        controls = ttk.Frame(self, padding=(12, 0, 12, 12))
        controls.grid(row=1, column=0, sticky="ew")
        for column in range(8):
            controls.columnconfigure(column, weight=0)
        controls.columnconfigure(7, weight=1)

        ttk.Label(controls, text="Channel").grid(row=0, column=0, sticky="w")
        channel_picker = ttk.Combobox(
            controls,
            state="readonly",
            width=8,
            values=tuple(self.available_bands),
            textvariable=self.selected_band,
        )
        channel_picker.grid(row=0, column=1, sticky="w", padx=(6, 18))
        channel_picker.bind("<<ComboboxSelected>>", self.on_channel_selected)

        ttk.Label(controls, text="Step").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(controls, from_=0.1, to=50.0, increment=0.5, width=7, textvariable=self.step).grid(
            row=0,
            column=3,
            sticky="w",
            padx=(6, 18),
        )

        ttk.Label(controls, text="X").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(controls, from_=-500.0, to=500.0, increment=0.5, width=8, textvariable=self.dx).grid(
            row=0,
            column=5,
            sticky="w",
            padx=(6, 10),
        )
        ttk.Label(controls, text="Y").grid(row=0, column=6, sticky="w")
        ttk.Spinbox(controls, from_=-500.0, to=500.0, increment=0.5, width=8, textvariable=self.dy).grid(
            row=0,
            column=7,
            sticky="w",
            padx=(6, 0),
        )

        arrows = ttk.Frame(controls)
        arrows.grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Button(arrows, text="Left", command=lambda: self.nudge(-self.step.get(), 0.0)).grid(row=1, column=0, padx=2)
        ttk.Button(arrows, text="Up", command=lambda: self.nudge(0.0, self.step.get())).grid(row=0, column=1, padx=2)
        ttk.Button(arrows, text="Down", command=lambda: self.nudge(0.0, -self.step.get())).grid(row=1, column=1, padx=2)
        ttk.Button(arrows, text="Right", command=lambda: self.nudge(self.step.get(), 0.0)).grid(row=1, column=2, padx=2)

        actions = ttk.Frame(controls)
        actions.grid(row=1, column=4, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(actions, text="Update preview", command=self.update_current_channel).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Reset channel", command=self.reset_channel).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Reset all", command=self.reset_all).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Save image", command=self.save_image).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Cancel", command=self.cancel).pack(side="left")

        ttk.Label(self, textvariable=self.status, padding=(12, 0, 12, 12)).grid(row=2, column=0, sticky="ew")

    def on_channel_selected(self, _event: object | None = None) -> None:
        band = self.selected_band.get()
        dx, dy = self.offsets.get(band, [0.0, 0.0])
        self.dx.set(dx)
        self.dy.set(dy)

    def current_offsets(self) -> dict[str, tuple[float, float]]:
        return {band: (values[0], values[1]) for band, values in self.offsets.items()}

    def store_current_channel(self) -> None:
        band = self.selected_band.get()
        if band:
            self.offsets[band] = [float(self.dx.get()), float(self.dy.get())]

    def update_current_channel(self) -> None:
        self.store_current_channel()
        self.render_preview()

    def nudge(self, dx: float, dy: float) -> None:
        self.dx.set(round(float(self.dx.get()) + dx, 2))
        self.dy.set(round(float(self.dy.get()) + dy, 2))
        self.update_current_channel()

    def reset_channel(self) -> None:
        band = self.selected_band.get()
        if not band:
            return
        self.offsets[band] = [0.0, 0.0]
        self.dx.set(0.0)
        self.dy.set(0.0)
        self.render_preview()

    def reset_all(self) -> None:
        for band in self.offsets:
            self.offsets[band] = [0.0, 0.0]
        self.on_channel_selected()
        self.render_preview()

    def render_preview(self) -> None:
        shifted = apply_channel_offsets(self.result.stacked, self.current_offsets())
        rgb = create_available_channel_rgb(shifted, stretch=5, q_value=8)

        fig, ax = plt.subplots(figsize=(8.5, 5.8), dpi=100, frameon=False)
        ax.imshow(rgb, origin="lower")
        ax.axis("off")
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        fig.savefig(self.preview_file, bbox_inches="tight", pad_inches=0, dpi=100)
        plt.close(fig)

        self.preview_image = tk.PhotoImage(file=self.preview_file)
        self.preview_label.configure(image=self.preview_image)
        offsets = ", ".join(
            f"{band}: x={values[0]:.2f}, y={values[1]:.2f}"
            for band, values in self.offsets.items()
        )
        self.status.set(f"Current manual offsets: {offsets}")

    def save_image(self) -> None:
        self.store_current_channel()
        shifted = apply_channel_offsets(self.result.stacked, self.current_offsets())
        self.result.stacked = shifted
        self.result.rgb = create_available_channel_rgb(shifted, stretch=5, q_value=8)
        save_rgb_image(self.result.rgb, self.result.output_file)
        self.parent.on_manual_alignment_saved(self.result, self.current_offsets())
        self.cleanup()
        self.destroy()

    def cancel(self) -> None:
        self.parent.on_manual_alignment_cancelled()
        self.cleanup()
        self.destroy()

    def cleanup(self) -> None:
        self.preview_tempdir.cleanup()


class ReductionApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Astronomical Image Reduction Tool")
        self.configure_app_icon()
        self.configure(bg=DARK_BG)
        self.configure_dark_theme()
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

    def configure_dark_theme(self) -> None:
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        default_font = font.nametofont("TkDefaultFont")
        button_font = default_font.copy()
        button_font.configure(weight="bold")
        brand_title_font = default_font.copy()
        brand_title_font.configure(size=20, weight="bold")
        brand_subtitle_font = default_font.copy()
        brand_subtitle_font.configure(size=12, weight="bold")

        self.style.configure(".", background=DARK_BG, foreground=TEXT)
        self.style.configure("TFrame", background=DARK_BG)
        self.style.configure("Panel.TFrame", background=PANEL_BG)
        self.style.configure("TLabel", background=DARK_BG, foreground=TEXT)
        self.style.configure("Panel.TLabel", background=PANEL_BG, foreground=TEXT)
        self.style.configure("Muted.TLabel", background=DARK_BG, foreground=MUTED_TEXT)
        self.style.configure("Logo.TLabel", background=PANEL_BG, foreground=TEXT)
        self.style.configure("BrandTitle.TLabel", background=PANEL_BG, foreground="#b9c7ea", font=brand_title_font)
        self.style.configure("BrandSubtitle.TLabel", background=PANEL_BG, foreground="#55c7ff", font=brand_subtitle_font)
        self.style.configure("Preview.TLabel", background=PANEL_BG, foreground=TEXT)
        self.style.configure("TLabelFrame", background=DARK_BG, foreground=MUTED_TEXT, bordercolor=BORDER, borderwidth=1, relief="flat")
        self.style.configure("TLabelFrame.Label", background=DARK_BG, foreground=MUTED_TEXT)
        self.style.configure("TEntry", fieldbackground=FIELD_BG, foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, insertcolor=TEXT, padding=(6, 5), relief="flat")
        self.style.configure("TCombobox", fieldbackground=FIELD_BG, foreground=TEXT, background=FIELD_BG, arrowcolor=MUTED_TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(6, 5), relief="flat")
        self.style.configure("Treeview", background=FIELD_BG, foreground=TEXT, fieldbackground=FIELD_BG, bordercolor=BORDER, borderwidth=0, relief="flat", rowheight=30)
        self.style.configure("Treeview.Heading", background=PANEL_BG, foreground=MUTED_TEXT, bordercolor=BORDER, borderwidth=0, relief="flat")
        self.style.configure("TButton", background=FIELD_BG, foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(14, 7), relief="flat")
        self.style.map("TButton", background=[("active", "#1a2540"), ("disabled", "#151b2b")], foreground=[("disabled", "#64708d")])
        self.style.map("TCombobox", fieldbackground=[("readonly", FIELD_BG)], foreground=[("readonly", TEXT)], background=[("readonly", FIELD_BG)])
        self.style.configure("Primary.TButton", background=ACCENT, foreground="#ffffff", font=button_font, padding=(18, 10), bordercolor=ACCENT, relief="flat")
        self.style.map("Primary.TButton", background=[("active", ACCENT_HOVER), ("disabled", "#1a2237")], foreground=[("disabled", "#66708a")])

    def maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            self.attributes("-zoomed", True)

    def configure_app_icon(self) -> None:
        assets_dir = Path(__file__).resolve().parent / "assets"
        icon_file = assets_dir / "airt-icon.ico"
        icon_png = assets_dir / "airt-icon.png"
        try:
            if icon_file.exists():
                self.iconbitmap(icon_file)
        except tk.TclError:
            pass

        try:
            if icon_png.exists():
                icon = Image.open(icon_png).convert("RGBA")
                self.app_icon_image = ImageTk.PhotoImage(icon.resize((256, 256), Image.Resampling.LANCZOS))
                self.header_icon_image = ImageTk.PhotoImage(icon.resize((HEADER_ICON_SIZE, HEADER_ICON_SIZE), Image.Resampling.LANCZOS))
                self.iconphoto(True, self.app_icon_image)
        except (tk.TclError, OSError):
            pass

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, padding=16, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        self._add_folder_picker(header, 0, "Bias folder", self.bias_dir, self.choose_bias_folder)
        self._add_folder_picker(header, 1, "Flat folder", self.flat_dir, self.choose_flat_folder)
        self._add_folder_picker(header, 2, "Object folder", self.object_dir, self.choose_object_folder)
        self._add_folder_picker(header, 3, "Output folder", self.output_dir, self.choose_output_folder)

        ttk.Label(header, text="Object name", style="Panel.TLabel").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(header, textvariable=self.object_name).grid(row=4, column=1, sticky="ew", padx=8, pady=(10, 0))

        ttk.Label(header, text="Alignment mode", style="Panel.TLabel").grid(row=5, column=0, sticky="w", pady=(10, 0))
        alignment_options = {
            "Automatic band alignment": ALIGNMENT_AUTOMATIC,
            "Manual band adjustment": ALIGNMENT_MANUAL,
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

        if hasattr(self, "header_icon_image"):
            brand = ttk.Frame(header, style="Panel.TFrame")
            brand.grid(row=0, column=3, rowspan=6, padx=(34, 18), sticky="e")
            brand.columnconfigure(1, weight=1)
            ttk.Label(brand, image=self.header_icon_image, style="Logo.TLabel").grid(
                row=0,
                column=0,
                rowspan=2,
                sticky="e",
                padx=(0, 18),
            )
            ttk.Label(brand, text="Astronomical", style="BrandTitle.TLabel").grid(
                row=0,
                column=1,
                sticky="sw",
            )
            ttk.Label(brand, text="Image Reduction Tool", style="BrandSubtitle.TLabel").grid(
                row=1,
                column=1,
                sticky="nw",
            )

        actions = ttk.Frame(self, padding=(16, 14, 16, 14))
        actions.grid(row=1, column=0, sticky="ew")
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
        ttk.Label(log_frame, textvariable=self.status, style="Muted.TLabel").grid(row=0, column=0, sticky="w")

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
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=pady)
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
        label = "manual" if getattr(result, "alignment_mode", "") == ALIGNMENT_MANUAL else "automatic"
        return f"Band alignment: {label}, reference {reference}; {detail}."

    def format_manual_offsets(self, offsets: dict[str, tuple[float, float]]) -> str:
        details = "; ".join(
            f"{band}: x={dx:.2f}, y={dy:.2f}"
            for band, (dx, dy) in offsets.items()
            if dx != 0 or dy != 0
        )
        return details or "no manual offsets"

    def open_manual_alignment(self, result: object) -> None:
        self.status.set("Manual alignment ready. Adjust the preview, then save the image.")
        ManualAlignmentWindow(self, result)

    def on_manual_alignment_saved(self, result: object, offsets: dict[str, tuple[float, float]]) -> None:
        alignment_summary = self.format_alignment_summary(result)
        manual_summary = self.format_manual_offsets(offsets)
        message = f"Image saved to:\n{result.output_file}\n\n{alignment_summary}\nManual offsets: {manual_summary}."
        self.status.set(f"Image saved to: {result.output_file}. Manual offsets: {manual_summary}.")
        messagebox.showinfo("Processing complete", message)

    def on_manual_alignment_cancelled(self) -> None:
        self.status.set("Manual alignment cancelled. No image was saved.")

    def run_reduction(self) -> None:
        try:
            object_name = self.object_name.get().strip() or "object"
            paths = self._project_paths()
            alignment_mode = self.alignment_mode.get()

            self.set_status("Processing bias, flats, alignment and RGB composition...")
            result = run_reduction(
                paths=paths,
                object_name=object_name,
                alignment_mode=alignment_mode,
            )

            if alignment_mode == ALIGNMENT_MANUAL:
                self.after(0, self.open_manual_alignment, result)
                return

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
