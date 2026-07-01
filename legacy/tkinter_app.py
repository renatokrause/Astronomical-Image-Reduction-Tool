from __future__ import annotations

import math
import threading
import webbrowser

import numpy as np
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

from PIL import Image, ImageDraw, ImageOps, ImageTk

from reduction_tool.calibration import read_fits_data
from reduction_tool.io import find_fits_files, group_by_filter
from reduction_tool.models import FILTERS, ProjectPaths
from reduction_tool.plotting import save_rgb_image
from reduction_tool.processing import (
    ALIGNMENT_AUTOMATIC,
    ALIGNMENT_MANUAL,
    ALIGNMENT_NONE,
    BACKGROUND_HYBRID,
    BACKGROUND_MEDIAN_GRID,
    BACKGROUND_OFF,
    BACKGROUND_POLYNOMIAL,
    CROP_AUTOMATIC,
    CROP_MANUAL,
    CROP_NONE,
    apply_final_export_adjustments,
    auto_object_mask_geometry,
    build_elliptical_object_mask,
    compose_linear_rgb,
    create_available_channel_rgb,
    final_stretch_rgb,
    crop_array,
    neutralize_rgb_background,
    normalise_preview,
    remove_band_background,
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
        self.geometry("1180x820")
        self.minsize(900, 640)
        self.configure_app_icon()
        self.configure(bg=DARK_BG)

        self.available_bands = [band for band in FILTERS if band in result.stacked]
        self.offsets = {band: [0.0, 0.0] for band in self.available_bands}
        self.selected_band = tk.StringVar(value=self.available_bands[0] if self.available_bands else "")
        self.step = tk.DoubleVar(value=1.0)
        self.dx = tk.DoubleVar(value=0.0)
        self.dy = tk.DoubleVar(value=0.0)
        self.status = tk.StringVar(value="Adjust a channel, then press Space or Update preview.")
        self.preview_is_stale = False
        self.preview_pil_image: Image.Image | None = None
        self.preview_image: ImageTk.PhotoImage | None = None
        self.zoom_level = 1.0
        self.min_zoom = 1.0
        self.max_zoom = 8.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.drag_start: tuple[int, int] | None = None
        self.drag_start_pan: tuple[float, float] = (0.0, 0.0)
        self.display_scale = 1.0
        self.display_origin: tuple[float, float] = (0.0, 0.0)
        self.measure_mode = False
        self.measure_points: list[tuple[float, float]] = []
        self.measure_line_id: int | None = None
        self.measure_marker_ids: list[int] = []

        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind_shortcuts()
        self.render_preview()
        self.after(50, self.maximize_window)
        self.after(100, self.focus_preview_update)
        self.grab_set()

    def maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            self.attributes("-zoomed", True)

    def configure_app_icon(self) -> None:
        try:
            if hasattr(self.parent, "app_icon_image"):
                self.iconphoto(True, self.parent.app_icon_image)
        except tk.TclError:
            pass

    def bind_shortcuts(self) -> None:
        self.bind_all("<Left>", lambda event: self.handle_key_nudge(event, -self.current_step(), 0.0))
        self.bind_all("<Right>", lambda event: self.handle_key_nudge(event, self.current_step(), 0.0))
        self.bind_all("<Up>", lambda event: self.handle_key_nudge(event, 0.0, self.current_step()))
        self.bind_all("<Down>", lambda event: self.handle_key_nudge(event, 0.0, -self.current_step()))
        self.bind_all("<Shift-Left>", lambda event: self.handle_key_nudge(event, -10.0, 0.0))
        self.bind_all("<Shift-Right>", lambda event: self.handle_key_nudge(event, 10.0, 0.0))
        self.bind_all("<Shift-Up>", lambda event: self.handle_key_nudge(event, 0.0, 10.0))
        self.bind_all("<Shift-Down>", lambda event: self.handle_key_nudge(event, 0.0, -10.0))
        self.bind_all("<space>", lambda _event: self.handle_update_preview())

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        preview_frame = ttk.Frame(self, padding=12, style="Panel.TFrame")
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            preview_frame,
            bg=PANEL_BG,
            highlightthickness=0,
            bd=0,
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", self.on_preview_resized)
        self.preview_canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.preview_canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.preview_canvas.bind("<MouseWheel>", self.on_mouse_wheel)

        controls = ttk.Frame(self, padding=(12, 0, 12, 12))
        controls.grid(row=1, column=0, sticky="ew")
        for column in range(8):
            controls.columnconfigure(column, weight=0)
        controls.columnconfigure(7, weight=1)

        ttk.Label(controls, text="Channel").grid(row=0, column=0, sticky="w")
        self.channel_picker = ttk.Combobox(
            controls,
            state="readonly",
            width=8,
            values=tuple(self.available_bands),
            textvariable=self.selected_band,
        )
        self.channel_picker.grid(row=0, column=1, sticky="w", padx=(6, 18))
        self.channel_picker.bind("<<ComboboxSelected>>", self.on_channel_selected)

        ttk.Label(controls, text="Step").grid(row=0, column=2, sticky="w")
        self.step_spinbox = self.create_number_spinbox(controls, self.step, 0.1, 50.0, 0.1, 7)
        for sequence in ("<Return>", "<FocusOut>", "<ButtonRelease-1>"):
            self.step_spinbox.bind(sequence, self.on_step_changed)
        self.step_spinbox.grid(
            row=0,
            column=3,
            sticky="w",
            padx=(6, 18),
        )

        ttk.Label(controls, text="X").grid(row=0, column=4, sticky="w")
        self.dx_spinbox = self.create_number_spinbox(controls, self.dx, -500.0, 500.0, 0.5, 8)
        self.dx_spinbox.grid(
            row=0,
            column=5,
            sticky="w",
            padx=(6, 10),
        )
        ttk.Label(controls, text="Y").grid(row=0, column=6, sticky="w")
        self.dy_spinbox = self.create_number_spinbox(controls, self.dy, -500.0, 500.0, 0.5, 8)
        self.dy_spinbox.grid(
            row=0,
            column=7,
            sticky="w",
            padx=(6, 0),
        )

        arrows = ttk.Frame(controls)
        arrows.grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Button(arrows, text="Left", command=lambda: self.nudge(-self.current_step(), 0.0)).grid(row=1, column=0, padx=2)
        ttk.Button(arrows, text="Up", command=lambda: self.nudge(0.0, self.current_step())).grid(row=0, column=1, padx=2)
        ttk.Button(arrows, text="Down", command=lambda: self.nudge(0.0, -self.current_step())).grid(row=1, column=1, padx=2)
        ttk.Button(arrows, text="Right", command=lambda: self.nudge(self.current_step(), 0.0)).grid(row=1, column=2, padx=2)

        view_tools = ttk.Frame(controls)
        view_tools.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Button(view_tools, text="Zoom out", command=self.zoom_out).pack(side="left", padx=(0, 8))
        ttk.Button(view_tools, text="Zoom in", command=self.zoom_in).pack(side="left", padx=(0, 8))
        ttk.Button(view_tools, text="Reset view", command=self.reset_view).pack(side="left", padx=(0, 8))
        self.measure_button = ttk.Button(view_tools, text="Measure", command=self.toggle_measure_mode)
        self.measure_button.pack(side="left")

        actions = ttk.Frame(controls)
        actions.grid(row=1, column=4, columnspan=4, sticky="e", pady=(10, 0))
        self.update_preview_button = ttk.Button(actions, text="Update preview (Space)", command=self.update_current_channel)
        self.update_preview_button.pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Reset channel", command=self.reset_channel).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Reset all", command=self.reset_all).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Confirm alignment", command=self.confirm_alignment).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Cancel", command=self.cancel).pack(side="left")

        ttk.Label(self, textvariable=self.status, style="Muted.TLabel", padding=(12, 0, 12, 12)).grid(
            row=2,
            column=0,
            sticky="ew",
        )

    def create_number_spinbox(
        self,
        parent: ttk.Frame,
        variable: tk.DoubleVar,
        from_value: float,
        to_value: float,
        increment: float,
        width: int,
    ) -> tk.Spinbox:
        spinbox = tk.Spinbox(
            parent,
            from_=from_value,
            to=to_value,
            increment=increment,
            width=width,
            textvariable=variable,
            bg=FIELD_BG,
            fg=TEXT,
            insertbackground=TEXT,
            buttonbackground=FIELD_BG,
            disabledbackground=FIELD_BG,
            readonlybackground=FIELD_BG,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            highlightthickness=1,
            relief="flat",
            bd=0,
        )
        for sequence in ("<Return>", "<FocusOut>", "<ButtonRelease-1>"):
            spinbox.bind(sequence, self.on_offset_control_changed)
        return spinbox

    def current_step(self) -> float:
        try:
            value = float(self.step_spinbox.get())
        except (AttributeError, tk.TclError, ValueError):
            value = float(self.step.get())
        value = max(0.1, min(50.0, value))
        self.step.set(value)
        return value

    def on_step_changed(self, _event: object | None = None) -> None:
        self.current_step()
        self.after_idle(self.focus_preview_update)

    def focus_preview_update(self) -> None:
        if hasattr(self, "update_preview_button"):
            self.update_preview_button.focus_set()

    def on_offset_control_changed(self, _event: object | None = None) -> None:
        self.mark_preview_stale()
        self.after_idle(self.focus_preview_update)

    def on_channel_selected(self, _event: object | None = None) -> None:
        band = self.selected_band.get()
        dx, dy = self.offsets.get(band, [0.0, 0.0])
        self.dx.set(dx)
        self.dy.set(dy)
        self.after_idle(self.focus_preview_update)

    def is_manual_input_widget(self, widget: object) -> bool:
        return widget in {
            getattr(self, "channel_picker", None),
            getattr(self, "step_spinbox", None),
            getattr(self, "dx_spinbox", None),
            getattr(self, "dy_spinbox", None),
        }

    def zoom_in(self) -> None:
        self.set_zoom(self.zoom_level * 1.25)

    def zoom_out(self) -> None:
        self.set_zoom(self.zoom_level / 1.25)

    def reset_view(self) -> None:
        self.zoom_level = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.clear_measurement()
        self.display_preview_image()
        self.status.set("View reset. Use Zoom in to inspect alignment details.")

    def set_zoom(self, zoom: float, center: tuple[int, int] | None = None) -> None:
        if self.preview_pil_image is None:
            return
        old_scale = self.display_scale
        old_origin_x, old_origin_y = self.display_origin
        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        if center is None:
            center = (canvas_width // 2, canvas_height // 2)
        image_x = (center[0] - old_origin_x) / old_scale if old_scale else 0.0
        image_y = (center[1] - old_origin_y) / old_scale if old_scale else 0.0

        self.zoom_level = min(self.max_zoom, max(self.min_zoom, zoom))
        image_width, image_height = self.preview_pil_image.size
        fit_scale = min(canvas_width / image_width, canvas_height / image_height)
        new_scale = fit_scale * self.zoom_level
        display_width = image_width * new_scale
        display_height = image_height * new_scale
        centered_x = (canvas_width - display_width) / 2
        centered_y = (canvas_height - display_height) / 2
        self.pan_x = center[0] - centered_x - (image_x * new_scale)
        self.pan_y = center[1] - centered_y - (image_y * new_scale)
        self.clamp_pan(display_width, display_height, canvas_width, canvas_height)
        self.display_preview_image()

    def on_mouse_wheel(self, event: tk.Event) -> str:
        if event.delta > 0:
            self.set_zoom(self.zoom_level * 1.15, (event.x, event.y))
        elif event.delta < 0:
            self.set_zoom(self.zoom_level / 1.15, (event.x, event.y))
        return "break"

    def on_canvas_press(self, event: tk.Event) -> str:
        if self.measure_mode:
            self.add_measurement_point(event.x, event.y)
            return "break"
        if self.zoom_level > 1.0:
            self.drag_start = (event.x, event.y)
            self.drag_start_pan = (self.pan_x, self.pan_y)
            self.preview_canvas.configure(cursor="fleur")
        return "break"

    def on_canvas_drag(self, event: tk.Event) -> str:
        if self.measure_mode or self.drag_start is None or self.preview_pil_image is None:
            return "break"
        start_x, start_y = self.drag_start
        start_pan_x, start_pan_y = self.drag_start_pan
        self.pan_x = start_pan_x + event.x - start_x
        self.pan_y = start_pan_y + event.y - start_y
        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        image_width, image_height = self.preview_pil_image.size
        self.clamp_pan(image_width * self.display_scale, image_height * self.display_scale, canvas_width, canvas_height)
        self.display_preview_image()
        return "break"

    def on_canvas_release(self, _event: tk.Event) -> str:
        self.drag_start = None
        self.preview_canvas.configure(cursor="crosshair" if self.measure_mode else "")
        return "break"

    def clamp_pan(self, display_width: float, display_height: float, canvas_width: int, canvas_height: int) -> None:
        max_pan_x = max(0.0, (display_width - canvas_width) / 2)
        max_pan_y = max(0.0, (display_height - canvas_height) / 2)
        self.pan_x = min(max_pan_x, max(-max_pan_x, self.pan_x))
        self.pan_y = min(max_pan_y, max(-max_pan_y, self.pan_y))

    def toggle_measure_mode(self) -> None:
        self.measure_mode = not self.measure_mode
        self.clear_measurement()
        if hasattr(self, "measure_button"):
            self.measure_button.configure(text="Measuring..." if self.measure_mode else "Measure")
        self.preview_canvas.configure(cursor="crosshair" if self.measure_mode else "")
        if self.measure_mode:
            self.status.set("Measure mode enabled. Click two points on the preview.")
        else:
            self.status.set("Measure mode disabled.")

    def clear_measurement(self) -> None:
        for item_id in self.measure_marker_ids:
            self.preview_canvas.delete(item_id)
        self.measure_marker_ids = []
        if self.measure_line_id is not None:
            self.preview_canvas.delete(self.measure_line_id)
            self.measure_line_id = None
        self.measure_points = []

    def add_measurement_point(self, canvas_x: int, canvas_y: int) -> None:
        image_point = self.canvas_to_image_point(canvas_x, canvas_y)
        if image_point is None:
            return
        if len(self.measure_points) >= 2:
            self.clear_measurement()
        self.measure_points.append(image_point)
        self.draw_measurement_overlay()
        if len(self.measure_points) == 2:
            first, second = self.measure_points
            display_dx = second[0] - first[0]
            display_dy = second[1] - first[1]
            suggested_dx = display_dx
            suggested_dy = -display_dy
            distance = math.hypot(display_dx, display_dy)
            self.status.set(
                f"Measured distance: {distance:.2f} px; suggested offset: "
                f"X={suggested_dx:.2f}, Y={suggested_dy:.2f}"
            )
            messagebox.showinfo(
                "Measurement",
                "Measured from first click to second click.\n\n"
                f"Distance: {distance:.2f} px\n"
                f"Display delta: X={display_dx:.2f} px, Y={display_dy:.2f} px\n\n"
                "Suggested offset for the selected channel:\n"
                f"X={suggested_dx:.2f}\n"
                f"Y={suggested_dy:.2f}",
                parent=self,
            )

    def canvas_to_image_point(self, canvas_x: int, canvas_y: int) -> tuple[float, float] | None:
        if self.preview_pil_image is None or self.display_scale <= 0:
            return None
        origin_x, origin_y = self.display_origin
        image_x = (canvas_x - origin_x) / self.display_scale
        image_y = (canvas_y - origin_y) / self.display_scale
        image_width, image_height = self.preview_pil_image.size
        if image_x < 0 or image_y < 0 or image_x > image_width or image_y > image_height:
            return None
        return image_x, image_y

    def image_to_canvas_point(self, image_x: float, image_y: float) -> tuple[float, float]:
        origin_x, origin_y = self.display_origin
        return origin_x + image_x * self.display_scale, origin_y + image_y * self.display_scale

    def draw_measurement_overlay(self) -> None:
        for item_id in self.measure_marker_ids:
            self.preview_canvas.delete(item_id)
        self.measure_marker_ids = []
        if self.measure_line_id is not None:
            self.preview_canvas.delete(self.measure_line_id)
            self.measure_line_id = None

        canvas_points = [self.image_to_canvas_point(x, y) for x, y in self.measure_points]
        for x, y in canvas_points:
            marker = self.preview_canvas.create_oval(
                x - 4,
                y - 4,
                x + 4,
                y + 4,
                outline=ACCENT,
                width=2,
            )
            self.measure_marker_ids.append(marker)
        if len(canvas_points) == 2:
            self.measure_line_id = self.preview_canvas.create_line(
                canvas_points[0][0],
                canvas_points[0][1],
                canvas_points[1][0],
                canvas_points[1][1],
                fill=ACCENT,
                width=2,
                dash=(6, 4),
            )
            self.preview_canvas.tag_raise(self.measure_line_id)

    def current_offsets(self) -> dict[str, tuple[float, float]]:
        return {band: (values[0], values[1]) for band, values in self.offsets.items()}

    def store_current_channel(self) -> None:
        band = self.selected_band.get()
        if band:
            self.offsets[band] = [float(self.dx.get()), float(self.dy.get())]

    def update_current_channel(self) -> None:
        self.store_current_channel()
        self.render_preview()

    def handle_update_preview(self) -> str:
        self.update_current_channel()
        return "break"

    def mark_preview_stale(self) -> None:
        self.store_current_channel()
        self.preview_is_stale = True
        offsets = ", ".join(
            f"{band}: x={values[0]:.2f}, y={values[1]:.2f}"
            for band, values in self.offsets.items()
        )
        self.status.set(f"Pending manual offsets: {offsets}. Press Space or Update preview.")

    def handle_key_nudge(self, event: tk.Event, dx: float, dy: float) -> str:
        if self.is_manual_input_widget(event.widget):
            if event.widget == getattr(self, "channel_picker", None):
                self.after_idle(self.focus_preview_update)
            elif event.widget == getattr(self, "step_spinbox", None):
                self.after_idle(self.on_step_changed)
            else:
                self.after_idle(self.on_offset_control_changed)
            return "break"
        self.nudge(dx, dy)
        return "break"

    def nudge(self, dx: float, dy: float) -> None:
        self.dx.set(round(float(self.dx.get()) + dx, 2))
        self.dy.set(round(float(self.dy.get()) + dy, 2))
        self.mark_preview_stale()

    def reset_channel(self) -> None:
        band = self.selected_band.get()
        if not band:
            return
        self.offsets[band] = [0.0, 0.0]
        self.dx.set(0.0)
        self.dy.set(0.0)
        self.mark_preview_stale()

    def reset_all(self) -> None:
        for band in self.offsets:
            self.offsets[band] = [0.0, 0.0]
        self.on_channel_selected()
        self.mark_preview_stale()

    def render_preview(self) -> None:
        shifted = apply_channel_offsets(self.result.stacked, self.current_offsets())
        rgb = create_available_channel_rgb(shifted, stretch=5, q_value=8)
        self.preview_pil_image = ImageOps.flip(Image.fromarray(rgb).convert("RGB"))
        self.preview_is_stale = False
        self.display_preview_image()
        offsets = ", ".join(
            f"{band}: x={values[0]:.2f}, y={values[1]:.2f}"
            for band, values in self.offsets.items()
        )
        self.status.set(f"Current manual offsets: {offsets}")

    def on_preview_resized(self, _event: tk.Event) -> None:
        self.display_preview_image()

    def display_preview_image(self) -> None:
        if self.preview_pil_image is None:
            return

        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        image_width, image_height = self.preview_pil_image.size
        fit_scale = min(canvas_width / image_width, canvas_height / image_height)
        self.display_scale = fit_scale * self.zoom_level
        display_width = max(1, int(image_width * self.display_scale))
        display_height = max(1, int(image_height * self.display_scale))
        self.clamp_pan(display_width, display_height, canvas_width, canvas_height)
        origin_x = ((canvas_width - display_width) / 2) + self.pan_x
        origin_y = ((canvas_height - display_height) / 2) + self.pan_y
        self.display_origin = (origin_x, origin_y)

        preview = self.preview_pil_image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        self.preview_image = ImageTk.PhotoImage(preview)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(
            origin_x,
            origin_y,
            image=self.preview_image,
            anchor="nw",
        )
        self.draw_measurement_overlay()

    def confirm_alignment(self) -> None:
        self.store_current_channel()
        shifted = apply_channel_offsets(self.result.stacked, self.current_offsets())
        self.result.stacked = shifted
        self.result.rgb = create_available_channel_rgb(shifted, stretch=5, q_value=8)
        self.parent.on_manual_alignment_confirmed(self.result, self.current_offsets())
        self.cleanup()
        self.destroy()

    def cancel(self) -> None:
        self.parent.on_manual_alignment_cancelled()
        self.cleanup()
        self.destroy()


    def cleanup(self) -> None:
        for sequence in ("<Left>", "<Right>", "<Up>", "<Down>", "<Shift-Left>", "<Shift-Right>", "<Shift-Up>", "<Shift-Down>", "<space>"):
            self.unbind_all(sequence)


class BackgroundCorrectionWindow(tk.Toplevel):
    def __init__(
        self,
        parent: "ReductionApp",
        result: object,
        manual_offsets: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.result = result
        self.manual_offsets = manual_offsets
        self.title("Background correction preview")
        self.geometry("1280x900")
        self.minsize(980, 720)
        self.configure_app_icon()
        self.configure(bg=DARK_BG)

        self.source_stacked = {band: np.array(image, copy=True) for band, image in result.stacked.items()}
        self.preview_image: ImageTk.PhotoImage | None = None
        self.preview_pil_image: Image.Image | None = None
        self.preview_geometry: tuple[float, float, float, int, int] | None = None
        self.drag_start: tuple[float, float] | None = None
        self.last_result: dict[str, object] | None = None

        center_x, center_y, axis_a, axis_b, angle = self.default_object_geometry()
        self.preview_mode = tk.StringVar(value="Final stretched")
        self.method_label = tk.StringVar(value="Hybrid")
        self.correction_strength = tk.DoubleVar(value=1.0)
        self.grid_size = tk.IntVar(value=128)
        self.smoothing_sigma = tk.DoubleVar(value=5.0)
        self.polynomial_order = tk.IntVar(value=2)
        self.star_sigma_threshold = tk.DoubleVar(value=5.0)
        self.star_mask_dilation_px = tk.IntVar(value=2)
        self.sigma_clip_enabled = tk.BooleanVar(value=True)
        self.sigma_clip_sigma = tk.DoubleVar(value=3.0)
        self.protect_object = tk.BooleanVar(value=True)
        self.auto_object_mask = tk.BooleanVar(value=True)
        self.show_mask_overlay = tk.BooleanVar(value=True)
        self.object_center_x = tk.DoubleVar(value=center_x)
        self.object_center_y = tk.DoubleVar(value=center_y)
        self.object_axis_a = tk.DoubleVar(value=axis_a)
        self.object_axis_b = tk.DoubleVar(value=axis_b)
        self.object_angle = tk.DoubleVar(value=angle)
        self.enable_neutralization = tk.BooleanVar(value=True)
        self.neutralization_strength = tk.DoubleVar(value=1.0)
        self.use_sky_mask_only = tk.BooleanVar(value=True)
        fallback_shape = next(iter(self.source_stacked.values())).shape
        self.crop_mode_label = tk.StringVar(value="Automatic crop")
        self.valid_field_crop_margin = tk.IntVar(value=20)
        self.valid_field_max_crop_percent = tk.DoubleVar(value=20.0)
        self.manual_crop_x0 = tk.IntVar(value=0)
        self.manual_crop_y0 = tk.IntVar(value=0)
        self.manual_crop_x1 = tk.IntVar(value=fallback_shape[1])
        self.manual_crop_y1 = tk.IntVar(value=fallback_shape[0])
        self.enable_final_color_balance = tk.BooleanVar(value=True)
        self.final_color_balance_strength = tk.DoubleVar(value=0.5)
        self.enable_luminance_enhance = tk.BooleanVar(value=True)
        self.luminance_enhance_amount = tk.DoubleVar(value=0.15)
        self.status = tk.StringVar(value="Update the preview to remove band gradients and neutralize the RGB background.")
        self.stats_text = tk.StringVar(value="No preview calculated yet.")

        self.method_values = {
            "Off": BACKGROUND_OFF,
            "Median grid": BACKGROUND_MEDIAN_GRID,
            "Polynomial": BACKGROUND_POLYNOMIAL,
            "Hybrid": BACKGROUND_HYBRID,
        }
        self.preview_modes = (
            "Original stretched",
            "Star/object mask",
            "Background model R",
            "Background model G/V",
            "Background model B",
            "Corrected bands",
            "RGB before neutralization",
            "RGB after neutralization",
            "Final uncropped",
            "Final color balanced",
            "Final enhanced",
            "Valid field mask",
            "Crop overlay",
            "Final cropped",
            "Before/After crop",
            "Before/After same stretch",        )

        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.after(50, self.maximize_window)
        self.after(100, self.update_button.focus_set)
        self.bind_all("<space>", lambda _event: self.handle_update_preview())
        self.render_preview()
        self.grab_set()

    def configure_app_icon(self) -> None:
        try:
            if hasattr(self.parent, "app_icon_image"):
                self.iconphoto(True, self.parent.app_icon_image)
        except tk.TclError:
            pass

    def maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            self.attributes("-zoomed", True)

    def default_object_geometry(self) -> tuple[float, float, float, float, float]:
        linear_rgb = compose_linear_rgb(self.source_stacked)
        luminance = np.median(linear_rgb, axis=2)
        geometry = auto_object_mask_geometry(luminance)
        center_x, center_y = geometry["center"]
        axis_a, axis_b = geometry["axes"]
        return float(center_x), float(center_y), float(axis_a), float(axis_b), float(geometry.get("angle", 0.0))

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        mode_bar = ttk.Frame(self, padding=(12, 12, 12, 6), style="Panel.TFrame")
        mode_bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(mode_bar, text="Preview mode").pack(side="left", padx=(0, 8))
        for mode in self.preview_modes:
            ttk.Radiobutton(mode_bar, text=mode, value=mode, variable=self.preview_mode, command=self.display_preview_image).pack(side="left", padx=(0, 8))

        preview_frame = ttk.Frame(self, padding=12, style="Panel.TFrame")
        preview_frame.grid(row=1, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(preview_frame, bg=PANEL_BG, highlightthickness=0, bd=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda _event: self.display_preview_image())
        self.preview_canvas.bind("<ButtonPress-1>", self.start_object_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self.finish_object_drag)

        controls = ttk.Frame(self, padding=(12, 6, 12, 8))
        controls.grid(row=2, column=0, sticky="ew")
        self._build_background_controls(controls, 0)
        self._build_object_controls(controls, 1)
        self._build_neutralization_controls(controls, 2)
        self._build_final_export_controls(controls, 3)
        self._build_stats_controls(controls, 4)

        actions = ttk.Frame(self, padding=(12, 0, 12, 12))
        actions.grid(row=3, column=0, sticky="ew")
        self.update_button = ttk.Button(actions, text="Update preview", command=self.render_preview)
        self.update_button.pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Apply", command=self.apply).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Save debug", command=self.save_debug_images).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Label(actions, textvariable=self.status, style="Muted.TLabel").pack(side="left", padx=(12, 0), fill="x", expand=True)

    def _section(self, parent: ttk.Frame, title: str, row: int) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text=title, padding=8)
        frame.grid(row=row, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        return frame

    def _spin(self, parent: ttk.Frame, variable: tk.Variable, from_value: float, to_value: float, increment: float, width: int = 7) -> tk.Spinbox:
        return tk.Spinbox(
            parent,
            from_=from_value,
            to=to_value,
            increment=increment,
            width=width,
            textvariable=variable,
            bg=FIELD_BG,
            fg=TEXT,
            insertbackground=TEXT,
            buttonbackground=FIELD_BG,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            highlightthickness=1,
            relief="flat",
            bd=0,
        )

    def _build_background_controls(self, parent: ttk.Frame, row: int) -> None:
        frame = self._section(parent, "Background correction", row)
        ttk.Label(frame, text="Method").grid(row=0, column=0, sticky="w")
        ttk.Combobox(frame, state="readonly", values=tuple(self.method_values.keys()), textvariable=self.method_label, width=16).grid(row=0, column=1, sticky="w", padx=(6, 14))
        for col, (label, var, start, end, step) in enumerate((
            ("Strength", self.correction_strength, 0.0, 1.2, 0.05),
            ("Grid", self.grid_size, 32, 512, 16),
            ("Smooth", self.smoothing_sigma, 0.0, 30.0, 0.5),
            ("Order", self.polynomial_order, 0, 4, 1),
            ("Star sigma", self.star_sigma_threshold, 0.5, 20.0, 0.1),
            ("Dilation", self.star_mask_dilation_px, 0, 20, 1),
        ), start=2):
            ttk.Label(frame, text=label).grid(row=0, column=col * 2, sticky="w")
            self._spin(frame, var, start, end, step).grid(row=0, column=col * 2 + 1, sticky="w", padx=(6, 14))
        ttk.Checkbutton(frame, text="Sigma clip", variable=self.sigma_clip_enabled).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(frame, text="Clip sigma").grid(row=1, column=1, sticky="w", pady=(6, 0))
        self._spin(frame, self.sigma_clip_sigma, 0.5, 10.0, 0.1).grid(row=1, column=2, sticky="w", padx=(6, 14), pady=(6, 0))

    def _build_object_controls(self, parent: ttk.Frame, row: int) -> None:
        frame = self._section(parent, "Object protection", row)
        ttk.Checkbutton(frame, text="Protect object", variable=self.protect_object).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(frame, text="Auto object mask", variable=self.auto_object_mask).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Show mask overlay", variable=self.show_mask_overlay, command=self.display_preview_image).grid(row=0, column=2, sticky="w")
        labels = (("Center X", self.object_center_x), ("Center Y", self.object_center_y), ("Axis A", self.object_axis_a), ("Axis B", self.object_axis_b), ("Angle", self.object_angle))
        for index, (label, var) in enumerate(labels):
            ttk.Label(frame, text=label).grid(row=1, column=index * 2, sticky="w", pady=(6, 0))
            self._spin(frame, var, -10000, 10000, 1, 8).grid(row=1, column=index * 2 + 1, sticky="w", padx=(6, 12), pady=(6, 0))

    def _build_neutralization_controls(self, parent: ttk.Frame, row: int) -> None:
        frame = self._section(parent, "RGB neutralization", row)
        ttk.Checkbutton(frame, text="Enable neutralization", variable=self.enable_neutralization).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(frame, text="Use sky mask only", variable=self.use_sky_mask_only).grid(row=0, column=1, sticky="w")
        ttk.Label(frame, text="Strength").grid(row=0, column=2, sticky="w")
        self._spin(frame, self.neutralization_strength, 0.0, 1.0, 0.05).grid(row=0, column=3, sticky="w", padx=(6, 12))

    def _build_final_export_controls(self, parent: ttk.Frame, row: int) -> None:
        frame = self._section(parent, "Final export", row)
        crop_options = {
            "No crop": CROP_NONE,
            "Automatic crop": CROP_AUTOMATIC,
            "Manual crop": CROP_MANUAL,
        }
        self.crop_mode_values = crop_options
        ttk.Label(frame, text="Crop").grid(row=0, column=0, sticky="w")
        ttk.Combobox(frame, state="readonly", values=tuple(crop_options.keys()), textvariable=self.crop_mode_label, width=16).grid(row=0, column=1, sticky="w", padx=(6, 14))
        ttk.Label(frame, text="Margin").grid(row=0, column=2, sticky="w")
        self._spin(frame, self.valid_field_crop_margin, 0, 200, 1).grid(row=0, column=3, sticky="w", padx=(6, 14))
        ttk.Label(frame, text="Max crop %").grid(row=0, column=4, sticky="w")
        self._spin(frame, self.valid_field_max_crop_percent, 0, 45, 1).grid(row=0, column=5, sticky="w", padx=(6, 14))
        ttk.Checkbutton(frame, text="Final color balance", variable=self.enable_final_color_balance).grid(row=0, column=6, sticky="w")
        ttk.Label(frame, text="Strength").grid(row=0, column=7, sticky="w")
        self._spin(frame, self.final_color_balance_strength, 0.0, 1.0, 0.05).grid(row=0, column=8, sticky="w", padx=(6, 14))
        ttk.Checkbutton(frame, text="Luminance contrast", variable=self.enable_luminance_enhance).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(frame, text="Amount").grid(row=1, column=1, sticky="w", pady=(6, 0))
        self._spin(frame, self.luminance_enhance_amount, 0.0, 0.5, 0.01).grid(row=1, column=2, sticky="w", padx=(6, 14), pady=(6, 0))
        for index, (label, var) in enumerate((("X0", self.manual_crop_x0), ("Y0", self.manual_crop_y0), ("X1", self.manual_crop_x1), ("Y1", self.manual_crop_y1))):
            ttk.Label(frame, text=label).grid(row=1, column=3 + index * 2, sticky="w", pady=(6, 0))
            self._spin(frame, var, 0, 10000, 1, 8).grid(row=1, column=4 + index * 2, sticky="w", padx=(6, 10), pady=(6, 0))

    def _build_stats_controls(self, parent: ttk.Frame, row: int) -> None:
        frame = self._section(parent, "Stats", row)
        ttk.Label(frame, textvariable=self.stats_text, style="Muted.TLabel", justify="left").pack(anchor="w")

    def current_method(self) -> str:
        return self.method_values.get(self.method_label.get(), BACKGROUND_HYBRID)

    def current_crop_mode(self) -> str:
        values = getattr(self, "crop_mode_values", {"Automatic crop": CROP_AUTOMATIC})
        return values.get(self.crop_mode_label.get(), CROP_AUTOMATIC)

    def manual_crop_box(self) -> tuple[int, int, int, int]:
        return (
            int(self.manual_crop_x0.get()),
            int(self.manual_crop_y0.get()),
            int(self.manual_crop_x1.get()),
            int(self.manual_crop_y1.get()),
        )

    def object_mask(self) -> np.ndarray | None:
        if not self.protect_object.get():
            return None
        fallback = next(iter(self.source_stacked.values()))
        if self.auto_object_mask.get():
            center_x, center_y, axis_a, axis_b, angle = self.default_object_geometry()
            source = "auto_central_region"
        else:
            center_x = float(self.object_center_x.get())
            center_y = float(self.object_center_y.get())
            axis_a = float(self.object_axis_a.get())
            axis_b = float(self.object_axis_b.get())
            angle = float(self.object_angle.get())
            source = "manual"
        self.current_object_geometry = {
            "center": [center_x, center_y],
            "axes": [axis_a, axis_b],
            "angle": angle,
            "source": source,
        }
        return build_elliptical_object_mask(fallback.shape, (center_x, center_y), (axis_a, axis_b), angle)

    def process_preview(self) -> dict[str, object]:
        method = self.current_method()
        obj_mask = self.object_mask()
        corrected = {}
        background_models = {}
        masks = {}
        sky_masks = []
        band_stats = {}
        for band, image in self.source_stacked.items():
            result = remove_band_background(
                image,
                method=method,
                star_sigma_threshold=float(self.star_sigma_threshold.get()),
                star_mask_dilation_px=int(self.star_mask_dilation_px.get()),
                object_mask=obj_mask,
                grid_size=int(self.grid_size.get()),
                smoothing_sigma=float(self.smoothing_sigma.get()),
                polynomial_order=int(self.polynomial_order.get()),
                sigma_clip=bool(self.sigma_clip_enabled.get()),
                sigma_clip_sigma=float(self.sigma_clip_sigma.get()),
                correction_strength=float(self.correction_strength.get()),
                debug=True,
            )
            corrected[band] = result["corrected"]
            background_models[band] = result["background_model"]
            masks[band] = result["mask"]
            sky_masks.append(result["sky_mask"])
            band_stats[band] = result["stats"]
        sky_mask = np.logical_and.reduce(sky_masks) if sky_masks else np.ones(next(iter(self.source_stacked.values())).shape, dtype=bool)
        rgb_original = compose_linear_rgb(self.source_stacked)
        rgb_before = compose_linear_rgb(corrected)
        if self.enable_neutralization.get():
            neutral_mask = sky_mask if self.use_sky_mask_only.get() else np.ones(sky_mask.shape, dtype=bool)
            rgb_after, neutral_stats = neutralize_rgb_background(rgb_before, neutral_mask, strength=float(self.neutralization_strength.get()))
        else:
            rgb_after = rgb_before
            neutral_stats = {"background_median_before": [0, 0, 0], "background_median_after": [0, 0, 0], "strength": 0.0}
        final_uncropped, stretch_stats = final_stretch_rgb(rgb_after, sky_mask=sky_mask, stretch_strength=8)
        original_stretched, _ = final_stretch_rgb(rgb_original, sky_mask=sky_mask, stretch_strength=8)
        final_adjustments = apply_final_export_adjustments(
            final_uncropped,
            sky_mask=sky_mask,
            crop_mode=self.current_crop_mode(),
            manual_crop_box=self.manual_crop_box(),
            crop_margin_px=int(self.valid_field_crop_margin.get()),
            crop_max_percent=float(self.valid_field_max_crop_percent.get()),
            color_balance=bool(self.enable_final_color_balance.get()),
            color_balance_strength=float(self.final_color_balance_strength.get()),
            enhance_luminance=bool(self.enable_luminance_enhance.get()),
            enhance_amount=float(self.luminance_enhance_amount.get()),
        )
        return {
            "corrected_stacked": corrected,
            "background_models": background_models,
            "masks": masks,
            "sky_mask": sky_mask,
            "rgb_original": rgb_original,
            "rgb_before_neutralization": rgb_before,
            "rgb_after_neutralization": rgb_after,
            "final_uncropped": final_uncropped,
            "final_color_balanced": final_adjustments["final_color_balanced"],
            "final_enhanced": final_adjustments["final_enhanced"],
            "final_stretched": final_adjustments["final"],
            "final_cropped": final_adjustments["final_cropped"],
            "valid_field_mask": final_adjustments["valid_field_mask"],
            "crop_overlay": final_adjustments["debug_images"]["crop_overlay"],
            "before_after_crop": final_adjustments["debug_images"]["before_after_crop"],
            "original_stretched": original_stretched,
            "stats": {
                "bands": band_stats,
                "rgb_neutralization": neutral_stats,
                "stretch": stretch_stats,
                "final_adjustments": final_adjustments["stats"],
                "crop_box": final_adjustments["stats"].get("crop_box"),
                "crop_percent_width": final_adjustments["stats"].get("crop_percent_width"),
                "crop_percent_height": final_adjustments["stats"].get("crop_percent_height"),
                "final_sky_median_before_color_balance": final_adjustments["stats"].get("final_sky_median_before_color_balance"),
                "final_sky_median_after_color_balance": final_adjustments["stats"].get("final_sky_median_after_color_balance"),
                "color_balance_factors": final_adjustments["stats"].get("color_balance_factors"),
                "gradient_metrics": {band: stats.get("gradient_metrics", {}) for band, stats in band_stats.items()},
                "object_mask": getattr(self, "current_object_geometry", {}),
            },
        }

    def render_preview(self) -> None:
        try:
            self.last_result = self.process_preview()
            self.update_stats()
            self.display_preview_image()
            self.status.set("Preview updated. Press Apply to save this correction.")
        except Exception as exc:
            self.status.set(f"Preview failed: {exc}")
            messagebox.showerror("Background correction error", str(exc), parent=self)

    def handle_update_preview(self) -> str:
        self.render_preview()
        self.update_button.focus_set()
        return "break"

    def update_stats(self) -> None:
        if not self.last_result:
            return
        lines = []
        for band in ("R", "V", "B"):
            stats = self.last_result["stats"]["bands"].get(band)
            if not stats:
                continue
            before = stats["before"]
            after = stats["after"]
            p_before = before["percentiles"]
            p_after = after["percentiles"]
            gradient = stats.get("gradient_metrics", {})
            lines.append(
                f"{band}: sky {stats['sky_pixels_used_percent']:.1f}% | "
                f"median {before['median']:.4g}->{after['median']:.4g} | "
                f"std {before['std']:.4g}->{after['std']:.4g} | "
                f"edge-center {float(gradient.get('edge_center_delta_before', 0.0)):.4g}->{float(gradient.get('edge_center_delta_after', 0.0)):.4g} "
                f"({float(gradient.get('gradient_reduction_percent', 0.0)):.1f}%) | "
                f"p1/50/99 {p_before[0]:.3g}/{p_before[1]:.3g}/{p_before[2]:.3g} -> {p_after[0]:.3g}/{p_after[1]:.3g}/{p_after[2]:.3g}"
            )
        neutral = self.last_result["stats"].get("rgb_neutralization", {})
        before_rgb = neutral.get("background_median_before", [0, 0, 0])
        after_rgb = neutral.get("background_median_after", [0, 0, 0])
        lines.append(f"RGB median before R/G/B: {before_rgb[0]:.4g} / {before_rgb[1]:.4g} / {before_rgb[2]:.4g}")
        lines.append(f"RGB median after R/G/B: {after_rgb[0]:.4g} / {after_rgb[1]:.4g} / {after_rgb[2]:.4g}")
        if before_rgb[0] and before_rgb[1]:
            lines.append(f"RGB ratios before: B/R={before_rgb[2] / before_rgb[0]:.3g}; B/G={before_rgb[2] / before_rgb[1]:.3g}")
        if after_rgb[0] and after_rgb[1]:
            lines.append(f"RGB ratios after: B/R={after_rgb[2] / after_rgb[0]:.3g}; B/G={after_rgb[2] / after_rgb[1]:.3g}")
        stretch = self.last_result["stats"].get("stretch", {})
        sky_after = stretch.get("sky_median_after_stretch", [0, 0, 0])
        lines.append(
            f"Final stretch sky median R/G/B: {sky_after[0]:.3f} / {sky_after[1]:.3f} / {sky_after[2]:.3f}; "
            f"clip low/high: {float(stretch.get('clipped_low_percent', 0.0)):.3f}% / {float(stretch.get('clipped_high_percent', 0.0)):.3f}%"
        )
        final_stats = self.last_result["stats"].get("final_adjustments", {})
        before_balance = final_stats.get("final_sky_median_before_color_balance", [0, 0, 0])
        after_balance = final_stats.get("final_sky_median_after_color_balance", [0, 0, 0])
        lines.append(f"Final color balance R/G/B: {before_balance[0]:.3f}/{before_balance[1]:.3f}/{before_balance[2]:.3f} -> {after_balance[0]:.3f}/{after_balance[1]:.3f}/{after_balance[2]:.3f}")
        lines.append(
            f"Crop box: {final_stats.get('crop_box', [0, 0, 0, 0])}; "
            f"crop W/H: {float(final_stats.get('crop_percent_width', 0.0)):.1f}% / {float(final_stats.get('crop_percent_height', 0.0)):.1f}%"
        )
        self.stats_text.set("\n".join(lines))

    def preview_array(self) -> np.ndarray:
        if not self.last_result:
            return normalise_preview(compose_linear_rgb(self.source_stacked))
        mode = self.preview_mode.get()
        if mode == "Original stretched":
            return np.asarray(self.last_result["original_stretched"], dtype=np.float32) / 255.0
        if mode == "Star/object mask":
            mask = np.zeros_like(next(iter(self.source_stacked.values())), dtype=bool)
            for item in self.last_result["masks"].values():
                mask |= np.asarray(item, dtype=bool)
            mask_rgb = np.dstack((mask.astype(np.float32), self.last_result["sky_mask"].astype(np.float32) * 0.45, mask.astype(np.float32) * 0.2))
            if self.show_mask_overlay.get():
                return np.clip(normalise_preview(compose_linear_rgb(self.source_stacked)) * 0.55 + mask_rgb * 0.75, 0, 1)
            return mask_rgb
        if mode == "Background model R":
            return normalise_preview(self.last_result["background_models"].get("R", next(iter(self.source_stacked.values()))))
        if mode == "Background model G/V":
            return normalise_preview(self.last_result["background_models"].get("V", next(iter(self.source_stacked.values()))))
        if mode == "Background model B":
            return normalise_preview(self.last_result["background_models"].get("B", next(iter(self.source_stacked.values()))))
        if mode == "Corrected bands":
            return normalise_preview(compose_linear_rgb(self.last_result["corrected_stacked"]))
        if mode == "RGB before neutralization":
            return normalise_preview(self.last_result["rgb_before_neutralization"])
        if mode == "RGB after neutralization":
            return normalise_preview(self.last_result["rgb_after_neutralization"])
        if mode == "Final uncropped":
            return np.asarray(self.last_result["final_uncropped"], dtype=np.float32) / 255.0
        if mode == "Final color balanced":
            return np.asarray(self.last_result["final_color_balanced"], dtype=np.float32) / 255.0
        if mode == "Final enhanced":
            return np.asarray(self.last_result["final_enhanced"], dtype=np.float32) / 255.0
        if mode == "Valid field mask":
            mask = np.asarray(self.last_result["valid_field_mask"], dtype=np.float32)
            return np.dstack((mask * 0.2, mask * 0.65, mask))
        if mode == "Crop overlay":
            return np.asarray(self.last_result["crop_overlay"], dtype=np.float32) / 255.0
        if mode == "Final cropped":
            return np.asarray(self.last_result["final_cropped"], dtype=np.float32) / 255.0
        if mode == "Before/After crop":
            return np.asarray(self.last_result["before_after_crop"], dtype=np.float32) / 255.0
        if mode == "Before/After same stretch":
            before, after = self.before_after_same_stretch(self.last_result["rgb_original"], self.last_result["rgb_after_neutralization"])
            separator = np.ones((before.shape[0], 4, 3), dtype=np.float32)
            return np.concatenate((before, separator, after), axis=1)
        return np.asarray(self.last_result["final_stretched"], dtype=np.float32) / 255.0

    def before_after_same_stretch(self, before_rgb: np.ndarray, after_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        combined = np.concatenate((before_rgb.reshape(-1, 3), after_rgb.reshape(-1, 3)), axis=0)
        lows = np.percentile(combined, 0.3, axis=0)
        highs = np.percentile(combined, 99.7, axis=0)
        highs = np.where(highs <= lows, lows + 1.0, highs)
        before = np.clip((before_rgb - lows.reshape(1, 1, 3)) / (highs - lows).reshape(1, 1, 3), 0, 1)
        after = np.clip((after_rgb - lows.reshape(1, 1, 3)) / (highs - lows).reshape(1, 1, 3), 0, 1)
        return before.astype(np.float32), after.astype(np.float32)

    def display_preview_image(self) -> None:
        array = self.preview_array()
        if array.ndim == 2:
            array = np.dstack((array, array, array))
        image = Image.fromarray(np.uint8(np.clip(array, 0, 1) * 255)).convert("RGB")
        self.preview_pil_image = ImageOps.flip(image)
        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        image_width, image_height = self.preview_pil_image.size
        scale = min(canvas_width / image_width, canvas_height / image_height)
        display_width = max(1, int(image_width * scale))
        display_height = max(1, int(image_height * scale))
        origin_x = (canvas_width - display_width) / 2
        origin_y = (canvas_height - display_height) / 2
        preview = self.preview_pil_image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        self.preview_image = ImageTk.PhotoImage(preview)
        self.preview_canvas.delete("all")
        self.preview_geometry = (origin_x, origin_y, scale, image_width, image_height)
        self.preview_canvas.create_image(origin_x, origin_y, image=self.preview_image, anchor="nw")
        self.draw_object_ellipse()

    def canvas_to_image(self, canvas_x: float, canvas_y: float) -> tuple[float, float] | None:
        if not self.preview_geometry:
            return None
        origin_x, origin_y, scale, image_width, image_height = self.preview_geometry
        image_x = (canvas_x - origin_x) / scale
        display_y = (canvas_y - origin_y) / scale
        image_y = image_height - 1 - display_y
        if image_x < 0 or image_y < 0 or image_x >= image_width or image_y >= image_height:
            return None
        return image_x, image_y

    def image_to_canvas(self, image_x: float, image_y: float) -> tuple[float, float] | None:
        if not self.preview_geometry:
            return None
        origin_x, origin_y, scale, _image_width, image_height = self.preview_geometry
        canvas_x = origin_x + image_x * scale
        canvas_y = origin_y + (image_height - 1 - image_y) * scale
        return canvas_x, canvas_y

    def start_object_drag(self, event: tk.Event) -> None:
        point = self.canvas_to_image(event.x, event.y)
        if point is not None:
            self.drag_start = point

    def finish_object_drag(self, event: tk.Event) -> None:
        if self.drag_start is None:
            return
        end = self.canvas_to_image(event.x, event.y)
        start = self.drag_start
        self.drag_start = None
        if end is None:
            return
        x0, y0 = start
        x1, y1 = end
        axis_a = abs(x1 - x0) / 2.0
        axis_b = abs(y1 - y0) / 2.0
        if axis_a < 4 or axis_b < 4:
            return
        self.auto_object_mask.set(False)
        self.object_center_x.set((x0 + x1) / 2.0)
        self.object_center_y.set((y0 + y1) / 2.0)
        self.object_axis_a.set(axis_a)
        self.object_axis_b.set(axis_b)
        self.object_angle.set(0.0)
        self.status.set("Manual object ellipse updated. Click Update preview to recalculate.")
        self.display_preview_image()

    def draw_object_ellipse(self) -> None:
        if not self.protect_object.get():
            return
        center = self.image_to_canvas(float(self.object_center_x.get()), float(self.object_center_y.get()))
        if center is None or not self.preview_geometry:
            return
        _origin_x, _origin_y, scale, _image_width, _image_height = self.preview_geometry
        cx, cy = center
        axis_a = max(1.0, float(self.object_axis_a.get()) * scale)
        axis_b = max(1.0, float(self.object_axis_b.get()) * scale)
        self.preview_canvas.create_oval(cx - axis_a, cy - axis_b, cx + axis_a, cy + axis_b, outline=ACCENT, width=2, dash=(5, 4))

    def corrected_stacked(self) -> dict[str, np.ndarray]:
        if self.last_result is None:
            self.render_preview()
        return dict((self.last_result or {}).get("corrected_stacked", self.source_stacked))

    def apply(self) -> None:
        if self.last_result is None:
            self.render_preview()
        corrected = self.corrected_stacked()
        self.result.stacked = corrected
        self.result.rgb = np.asarray((self.last_result or {}).get("final_stretched", create_available_channel_rgb(corrected, stretch=5, q_value=8)))
        self.result.background_correction = self.current_method()
        self.result.background_stats = (self.last_result or {}).get("stats", {})
        save_rgb_image(self.result.rgb, self.result.output_file)
        self.parent.on_background_correction_saved(self.result, self.manual_offsets)
        self.cleanup()
        self.destroy()

    def save_debug_images(self) -> None:
        if self.last_result is None:
            self.render_preview()
        folder = filedialog.askdirectory(title="Select debug output folder", parent=self)
        if not folder:
            return
        output_dir = Path(folder)
        for band in ("R", "V", "B"):
            if band not in self.source_stacked:
                continue
            Image.fromarray(np.uint8(normalise_preview(self.source_stacked[band]) * 255)).save(output_dir / f"band_{band}_original.png")
            Image.fromarray(np.uint8(np.asarray(self.last_result["masks"][band], dtype=np.float32) * 255)).save(output_dir / f"band_{band}_mask.png")
            Image.fromarray(np.uint8(normalise_preview(self.last_result["background_models"][band]) * 255)).save(output_dir / f"band_{band}_background_model.png")
            Image.fromarray(np.uint8(normalise_preview(self.last_result["corrected_stacked"][band]) * 255)).save(output_dir / f"band_{band}_corrected.png")
        Image.fromarray(np.uint8(normalise_preview(self.last_result["rgb_before_neutralization"]) * 255)).save(output_dir / "rgb_before_neutralization.png")
        Image.fromarray(np.uint8(normalise_preview(self.last_result["rgb_after_neutralization"]) * 255)).save(output_dir / "rgb_after_neutralization.png")
        Image.fromarray(np.asarray(self.last_result["final_uncropped"], dtype=np.uint8)).save(output_dir / "final_uncropped.png")
        Image.fromarray(np.asarray(self.last_result["final_color_balanced"], dtype=np.uint8)).save(output_dir / "final_color_balanced.png")
        Image.fromarray(np.asarray(self.last_result["final_enhanced"], dtype=np.uint8)).save(output_dir / "final_enhanced.png")
        Image.fromarray(np.asarray(self.last_result["valid_field_mask"], dtype=np.uint8) * 255).save(output_dir / "valid_field_mask.png")
        Image.fromarray(np.asarray(self.last_result["crop_overlay"], dtype=np.uint8)).save(output_dir / "crop_overlay.png")
        Image.fromarray(np.asarray(self.last_result["final_cropped"], dtype=np.uint8)).save(output_dir / "final_cropped.png")
        Image.fromarray(np.asarray(self.last_result["before_after_crop"], dtype=np.uint8)).save(output_dir / "before_after_crop.png")
        Image.fromarray(np.asarray(self.last_result["final_stretched"], dtype=np.uint8)).save(output_dir / "final_stretched.png")
        self.save_stretch_histogram(output_dir / "stretch_histogram_before_after.png")
        before, after = self.before_after_same_stretch(self.last_result["rgb_original"], self.last_result["rgb_after_neutralization"])
        before_after = np.concatenate((before, np.ones((before.shape[0], 4, 3), dtype=np.float32), after), axis=1)
        Image.fromarray(np.uint8(before_after * 255)).save(output_dir / "before_after_same_stretch.png")
        import json
        with open(output_dir / "processing_stats.json", "w", encoding="utf-8") as file:
            json.dump(self.last_result["stats"], file, indent=2)
        self.status.set(f"Debug images saved to: {output_dir}")

    def save_stretch_histogram(self, path: Path) -> None:
        stretch = (self.last_result or {}).get("stats", {}).get("stretch", {})
        before = stretch.get("histogram_before_stretch", {})
        after = stretch.get("histogram_after_stretch", {})
        before_counts = np.asarray(before.get("counts", []), dtype=float)
        after_counts = np.asarray(after.get("counts", []), dtype=float)
        width, height = 900, 360
        margin = 48
        image = Image.new("RGB", (width, height), PANEL_BG)
        draw = ImageDraw.Draw(image)
        draw.rectangle((margin, margin, width - margin, height - margin), outline=BORDER)
        draw.text((margin, 18), "Stretch histogram: before (blue) / after (accent)", fill=TEXT)
        max_count = max(float(before_counts.max()) if before_counts.size else 0.0, float(after_counts.max()) if after_counts.size else 0.0, 1.0)
        plot_width = width - margin * 2
        plot_height = height - margin * 2

        def draw_histogram(counts: np.ndarray, color: str) -> None:
            if counts.size == 0:
                return
            step = plot_width / counts.size
            points = []
            for index, count in enumerate(counts):
                x = margin + index * step
                y = height - margin - (count / max_count) * plot_height
                points.append((x, y))
            if len(points) > 1:
                draw.line(points, fill=color, width=2)

        draw_histogram(before_counts, "#4f8cff")
        draw_histogram(after_counts, "#5eead4")
        image.save(path)

    def cleanup(self) -> None:
        self.unbind_all("<space>")

    def cancel(self) -> None:
        self.parent.on_background_correction_cancelled()
        self.cleanup()
        self.destroy()

class ObjectFilterWindow(tk.Toplevel):
    def __init__(
        self,
        parent: "ReductionApp",
        files_by_band: dict[str, list[Path]],
        selected_files_by_band: dict[str, set[Path]] | None,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.files_by_band = files_by_band
        self.selection = {
            band: set(selected_files_by_band[band]) if selected_files_by_band and band in selected_files_by_band else set(files)
            for band, files in files_by_band.items()
        }
        self.variables: dict[Path, tk.BooleanVar] = {}
        self.preview_image: ImageTk.PhotoImage | None = None
        self.selected_band = tk.StringVar(value=self.first_available_band())
        self.status = tk.StringVar(value="Select the object files that should be used.")

        self.title("Object file filter")
        self.geometry("1180x820")
        self.minsize(900, 640)
        self.configure(bg=DARK_BG)
        self.configure_app_icon()
        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.after(50, self.maximize_window)
        self.render_file_list()
        self.update_preview()
        self.grab_set()

    def configure_app_icon(self) -> None:
        try:
            if hasattr(self.parent, "app_icon_image"):
                self.iconphoto(True, self.parent.app_icon_image)
        except tk.TclError:
            pass

    def maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            self.attributes("-zoomed", True)

    def first_available_band(self) -> str:
        for band in FILTERS:
            if self.files_by_band.get(band):
                return band
        return FILTERS[0]

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=12)
        left.grid(row=0, column=0, sticky="ns")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)

        ttk.Label(left, text="Band", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        band_picker = ttk.Combobox(
            left,
            state="readonly",
            values=tuple(FILTERS),
            textvariable=self.selected_band,
            width=12,
        )
        band_picker.grid(row=1, column=0, sticky="ew", pady=(6, 12))
        band_picker.bind("<<ComboboxSelected>>", self.on_band_selected)

        list_frame = ttk.Frame(left)
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.file_canvas = tk.Canvas(list_frame, width=420, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER)
        self.file_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.file_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.file_canvas.configure(yscrollcommand=scrollbar.set)
        self.file_list = ttk.Frame(self.file_canvas, padding=8)
        self.file_canvas.create_window((0, 0), window=self.file_list, anchor="nw")
        self.file_list.bind("<Configure>", lambda _event: self.file_canvas.configure(scrollregion=self.file_canvas.bbox("all")))

        actions = ttk.Frame(left)
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Select all", command=self.select_all_current_band).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Clear band", command=self.clear_current_band).pack(side="left")

        right = ttk.Frame(self, padding=(0, 12, 12, 12), style="Panel.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(right, bg=PANEL_BG, highlightthickness=0, bd=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda _event: self.update_preview())

        footer = ttk.Frame(right)
        footer.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="OK", command=self.ok).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(footer, text="Cancel", command=self.cancel).grid(row=0, column=2, padx=(8, 0))

    def on_band_selected(self, _event: object | None = None) -> None:
        self.render_file_list()
        self.update_preview()

    def current_band(self) -> str:
        return self.selected_band.get() or self.first_available_band()

    def render_file_list(self) -> None:
        for child in self.file_list.winfo_children():
            child.destroy()
        self.variables = {}

        band = self.current_band()
        files = self.files_by_band.get(band, [])
        if not files:
            ttk.Label(self.file_list, text="No object files for this band.", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
            return

        for row, file_path in enumerate(files):
            variable = tk.BooleanVar(value=file_path in self.selection.get(band, set()))
            self.variables[file_path] = variable
            check = tk.Checkbutton(
                self.file_list,
                text=file_path.name,
                variable=variable,
                command=self.on_file_toggled,
                bg=PANEL_BG,
                fg=TEXT,
                activebackground=PANEL_BG,
                activeforeground=TEXT,
                selectcolor=FIELD_BG,
                anchor="w",
                justify="left",
            )
            check.grid(row=row, column=0, sticky="ew", pady=2)

    def on_file_toggled(self) -> None:
        band = self.current_band()
        selected = {file_path for file_path, variable in self.variables.items() if variable.get()}
        self.selection[band] = selected
        self.update_preview()

    def select_all_current_band(self) -> None:
        band = self.current_band()
        self.selection[band] = set(self.files_by_band.get(band, []))
        self.render_file_list()
        self.update_preview()

    def clear_current_band(self) -> None:
        self.selection[self.current_band()] = set()
        self.render_file_list()
        self.update_preview()

    def update_preview(self) -> None:
        if not hasattr(self, "preview_canvas"):
            return
        band = self.current_band()
        selected = list(self.selection.get(band, set()))
        self.preview_canvas.delete("all")
        if not selected:
            self.status.set(f"{band} band: no files selected.")
            self.preview_canvas.create_text(
                max(1, self.preview_canvas.winfo_width()) // 2,
                max(1, self.preview_canvas.winfo_height()) // 2,
                text="No files selected",
                fill=MUTED_TEXT,
                font=("Segoe UI", 16),
            )
            return

        try:
            stack = [read_fits_data(file_path) for file_path in selected]
            preview_data = stack[0] if len(stack) == 1 else np.median(stack, axis=0)
            image = self.preview_to_image(preview_data)
        except Exception as exc:
            self.status.set(f"Preview failed for {band} band: {exc}")
            return

        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        image_width, image_height = image.size
        scale = min(canvas_width / image_width, canvas_height / image_height)
        display_width = max(1, int(image_width * scale))
        display_height = max(1, int(image_height * scale))
        image = image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        self.preview_image = ImageTk.PhotoImage(image)
        self.preview_canvas.create_image(
            canvas_width // 2,
            canvas_height // 2,
            image=self.preview_image,
            anchor="center",
        )
        total = len(self.files_by_band.get(band, []))
        self.status.set(f"{band} band: {len(selected)} of {total} object file(s) selected.")

    def preview_to_image(self, data: object) -> Image.Image:
        array = np.asarray(data, dtype=float)
        array = np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0)
        low, high = np.nanpercentile(array, [1, 99.5])
        if high <= low:
            low, high = float(np.nanmin(array)), float(np.nanmax(array))
        if high <= low:
            normalized = np.zeros_like(array, dtype=np.uint8)
        else:
            normalized = np.clip((array - low) / (high - low), 0, 1)
            normalized = (normalized * 255).astype(np.uint8)
        return ImageOps.flip(Image.fromarray(normalized, mode="L")).convert("RGB")

    def ok(self) -> None:
        self.parent.on_object_filter_saved(self.selection)
        self.destroy()

    def cancel(self) -> None:
        self.destroy()

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
        self.alignment_mode = tk.StringVar(value=ALIGNMENT_MANUAL)
        self.background_correction = tk.StringVar(value=BACKGROUND_OFF)
        self.background_correction_enabled = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Select the input and output folders to begin.")
        self.progress = tk.DoubleVar(value=0.0)
        self.object_file_selection: dict[str, set[Path]] | None = None
        self.object_filter_folder: Path | None = None

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
        brand_title_font.configure(size=24, weight="bold")
        brand_subtitle_font = default_font.copy()
        brand_subtitle_font.configure(size=14, weight="bold")
        brand_author_font = default_font.copy()
        brand_author_font.configure(size=5)

        self.style.configure(".", background=DARK_BG, foreground=TEXT)
        self.style.configure("TFrame", background=DARK_BG)
        self.style.configure("Panel.TFrame", background=PANEL_BG)
        self.style.configure("TLabel", background=DARK_BG, foreground=TEXT)
        self.style.configure("Panel.TLabel", background=PANEL_BG, foreground=TEXT)
        self.style.configure("Muted.TLabel", background=DARK_BG, foreground=MUTED_TEXT)
        self.style.configure("Logo.TLabel", background=PANEL_BG, foreground=TEXT)
        self.style.configure("BrandTitle.TLabel", background=PANEL_BG, foreground="#b9c7ea", font=brand_title_font)
        self.style.configure("BrandSubtitle.TLabel", background=PANEL_BG, foreground="#55c7ff", font=brand_subtitle_font)
        self.style.configure("BrandAuthor.TLabel", background=PANEL_BG, foreground=MUTED_TEXT, font=brand_author_font)
        self.style.configure("Preview.TLabel", background=PANEL_BG, foreground=TEXT)
        self.style.configure("Panel.TCheckbutton", background=PANEL_BG, foreground=TEXT, focuscolor=PANEL_BG)
        self.style.map("Panel.TCheckbutton", background=[("active", PANEL_BG)], foreground=[("disabled", "#64708d")])
        self.style.configure("TLabelFrame", background=DARK_BG, foreground=MUTED_TEXT, bordercolor=BORDER, borderwidth=1, relief="flat")
        self.style.configure("TLabelFrame.Label", background=DARK_BG, foreground=MUTED_TEXT)
        self.style.configure("TEntry", fieldbackground=FIELD_BG, foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, insertcolor=TEXT, padding=(6, 5), relief="flat")
        self.style.configure("TCombobox", fieldbackground=FIELD_BG, foreground=TEXT, background=FIELD_BG, arrowcolor=MUTED_TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(6, 5), relief="flat")
        self.style.configure("Treeview", background=FIELD_BG, foreground=TEXT, fieldbackground=FIELD_BG, bordercolor=BORDER, borderwidth=0, relief="flat", rowheight=30)
        self.style.configure("Treeview.Heading", background=PANEL_BG, foreground=MUTED_TEXT, bordercolor=BORDER, borderwidth=0, relief="flat")
        self.style.configure("TButton", background=FIELD_BG, foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(14, 7), relief="flat")
        self.style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=FIELD_BG, bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
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

    def open_author_github(self, _event: object | None = None) -> None:
        webbrowser.open_new_tab("https://github.com/ericBK26/")

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
        self.alignment_mode_picker.set("Manual band adjustment")
        self.alignment_mode_picker.bind("<<ComboboxSelected>>", self.on_alignment_mode_selected)

        ttk.Label(header, text="Background correction", style="Panel.TLabel").grid(row=6, column=0, sticky="w", pady=(10, 0))
        self.background_correction_toggle = ttk.Checkbutton(
            header,
            text="Enable background correction",
            variable=self.background_correction_enabled,
            command=self.on_background_correction_selected,
            style="Panel.TCheckbutton",
        )
        self.background_correction_toggle.grid(row=6, column=1, sticky="w", padx=8, pady=(10, 0))
        if hasattr(self, "header_icon_image"):
            brand = ttk.Frame(header, style="Panel.TFrame")
            brand.grid(row=0, column=3, rowspan=7, padx=(34, 18), sticky="e")
            brand.columnconfigure(1, weight=1)
            ttk.Label(brand, image=self.header_icon_image, style="Logo.TLabel").grid(
                row=0,
                column=0,
                rowspan=4,
                sticky="e",
                padx=(0, 18),
            )
            text_stack = tk.Frame(brand, bg=PANEL_BG, width=360, height=108)
            text_stack.grid(row=0, column=1, sticky="w")
            text_stack.grid_propagate(False)

            tk.Label(
                text_stack,
                text="Astronomical",
                bg=PANEL_BG,
                fg="#d9e4ff",
                font=("Segoe UI", 26, "bold"),
                borderwidth=0,
                highlightthickness=0,
                pady=0,
            ).place(x=0, y=0)
            tk.Label(
                text_stack,
                text="Image Reduction Tool",
                bg=PANEL_BG,
                fg="#55c7ff",
                font=("Segoe UI", 16, "bold"),
                borderwidth=0,
                highlightthickness=0,
                pady=0,
            ).place(x=0, y=39)
            tk.Label(
                text_stack,
                text="Author: Eric Bairros Krause",
                bg=PANEL_BG,
                fg=MUTED_TEXT,
                font=("Segoe UI", 9),
                borderwidth=0,
                highlightthickness=0,
                pady=0,
            ).place(x=0, y=72)
            author_link = tk.Label(
                text_stack,
                text="github.com/ericBK26 | bairros.krause@ufrgs.br",
                bg=PANEL_BG,
                fg=MUTED_TEXT,
                font=("Segoe UI", 9),
                borderwidth=0,
                highlightthickness=0,
                pady=0,
                cursor="hand2",
            )
            author_link.place(x=0, y=86)
            author_link.bind("<Button-1>", self.open_author_github)

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
        self.filter_button = ttk.Button(
            actions,
            text="Filter object files",
            command=self.open_object_filter,
            state="disabled",
        )
        self.filter_button.pack(side="left", padx=(12, 0))

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

        status_frame = ttk.LabelFrame(body, text="Status", padding=8)
        status_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.status, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(
            status_frame,
            variable=self.progress,
            maximum=100,
            mode="determinate",
            style="Horizontal.TProgressbar",
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self._reset_table()

    def on_alignment_mode_selected(self, _event: object | None = None) -> None:
        selected = self.alignment_mode_picker.get()
        self.alignment_mode.set(self.alignment_mode_labels.get(selected, ALIGNMENT_MANUAL))

    def on_background_correction_selected(self, _event: object | None = None) -> None:
        mode = BACKGROUND_HYBRID if self.background_correction_enabled.get() else BACKGROUND_OFF
        self.background_correction.set(mode)
        self.progress.set(0)

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
            self.object_file_selection = None
            self.object_filter_folder = None
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
        if hasattr(self, "progress"):
            self.progress.set(0)
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
                object_band_files = objects.get(band, [])
                object_count = self.object_count_label(band, object_band_files)
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
        if hasattr(self, "filter_button"):
            filter_state = "normal" if self.object_dir.get().strip() else "disabled"
            self.filter_button.configure(state=filter_state)

    def object_files_by_band(self) -> dict[str, list[Path]]:
        if not self.object_dir.get().strip():
            return {band: [] for band in FILTERS}
        return group_by_filter(find_fits_files(Path(self.object_dir.get())))

    def object_filter_matches_current_folder(self) -> bool:
        if self.object_filter_folder is None:
            return False
        return self.object_dir.get().strip() and self.object_filter_folder == Path(self.object_dir.get())

    def object_count_label(self, band: str, files: list[Path]) -> int | str:
        if self.object_file_selection is None or not self.object_filter_matches_current_folder():
            return len(files)
        available = set(files)
        selected = self.object_file_selection.get(band, set()) & available
        self.object_file_selection[band] = selected
        return f"{len(selected)}/{len(files)}"

    def selection_summary(self) -> str:
        if self.object_file_selection is None or not self.object_filter_matches_current_folder():
            return "all object files selected"
        parts = []
        files_by_band = self.object_files_by_band()
        for band in FILTERS:
            total = len(files_by_band.get(band, []))
            selected = len(self.object_file_selection.get(band, set()) & set(files_by_band.get(band, [])))
            if total:
                parts.append(f"{band}: {selected}/{total}")
        return "; ".join(parts) if parts else "no object files selected"

    def selected_object_file_lists(self) -> dict[str, list[Path]] | None:
        if self.object_file_selection is None or not self.object_filter_matches_current_folder():
            return None
        files_by_band = self.object_files_by_band()
        selected: dict[str, list[Path]] = {}
        for band in FILTERS:
            available = set(files_by_band.get(band, []))
            selected[band] = sorted(self.object_file_selection.get(band, set()) & available)
        return selected

    def open_object_filter(self) -> None:
        files_by_band = self.object_files_by_band()
        if not any(files_by_band.values()):
            messagebox.showerror("Object file filter", "Select an object folder with FITS files first.")
            return
        ObjectFilterWindow(self, files_by_band, self.object_file_selection)

    def on_object_filter_saved(self, selection: dict[str, set[Path]]) -> None:
        self.object_file_selection = {band: set(selection.get(band, set())) for band in FILTERS}
        self.object_filter_folder = Path(self.object_dir.get())
        self.scan_files_partial()
        self.status.set(f"Object file filter applied. {self.selection_summary()}.")

    def start_reduction(self) -> None:
        thread = threading.Thread(target=self.run_reduction, daemon=True)
        thread.start()

    def set_status(self, message: str) -> None:
        self.after(0, self.status.set, message)

    def set_progress(self, value: float) -> None:
        self.after(0, self.progress.set, max(0.0, min(100.0, value)))

    def update_progress(self, value: float, message: str) -> None:
        self.after(0, self.status.set, message)
        self.set_progress(value)

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

    def format_background_summary(self, result: object) -> str:
        mode = getattr(result, "background_correction", BACKGROUND_OFF)
        if mode == BACKGROUND_OFF:
            return "Background correction: off."
        stats = getattr(result, "background_stats", {}) or {}
        bands = stats.get("bands", {}) if isinstance(stats, dict) else {}
        details = []
        for band in ("R", "V", "B"):
            band_stats = bands.get(band) if isinstance(bands, dict) else None
            if not band_stats:
                continue
            before = band_stats.get("before", {})
            after = band_stats.get("after", {})
            details.append(
                f"{band} median {float(before.get('median', 0.0)):.4g}->{float(after.get('median', 0.0)):.4g}, "
                f"sky {float(band_stats.get('sky_pixels_used_percent', 0.0)):.1f}%"
            )
        neutral = stats.get("rgb_neutralization", {}) if isinstance(stats, dict) else {}
        before_rgb = neutral.get("background_median_before", [0, 0, 0])
        after_rgb = neutral.get("background_median_after", [0, 0, 0])
        detail = "; ".join(details) if details else "no band statistics"
        return (
            f"Background correction: {mode} ({detail}; "
            f"RGB before {before_rgb[0]:.4g}/{before_rgb[1]:.4g}/{before_rgb[2]:.4g}, "
            f"after {after_rgb[0]:.4g}/{after_rgb[1]:.4g}/{after_rgb[2]:.4g})."
        )
    def format_manual_offsets(self, offsets: dict[str, tuple[float, float]]) -> str:
        details = "; ".join(
            f"{band}: x={dx:.2f}, y={dy:.2f}"
            for band, (dx, dy) in offsets.items()
            if dx != 0 or dy != 0
        )
        return details or "no manual offsets"

    def open_manual_alignment(self, result: object) -> None:
        self.status.set("Manual alignment ready. Adjust the preview, then confirm the alignment.")
        self.progress.set(96)
        ManualAlignmentWindow(self, result)

    def on_manual_alignment_confirmed(self, result: object, offsets: dict[str, tuple[float, float]]) -> None:
        if getattr(result, "background_correction", BACKGROUND_OFF) == BACKGROUND_OFF:
            self.save_final_image(result, offsets)
            return
        self.open_background_correction(result, offsets)

    def open_background_correction(
        self,
        result: object,
        manual_offsets: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        self.status.set("Background correction preview ready. Adjust the preview, then save the image.")
        self.progress.set(98)
        BackgroundCorrectionWindow(self, result, manual_offsets)

    def save_final_image(
        self,
        result: object,
        manual_offsets: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        save_rgb_image(result.rgb, result.output_file)
        self.on_background_correction_saved(result, manual_offsets)

    def on_background_correction_saved(
        self,
        result: object,
        manual_offsets: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        alignment_summary = self.format_alignment_summary(result)
        background_summary = self.format_background_summary(result)
        manual_summary = self.format_manual_offsets(manual_offsets or {})
        manual_line = f"\nManual offsets: {manual_summary}." if manual_offsets is not None else ""
        message = f"Image saved to:\n{result.output_file}\n\n{alignment_summary}\n{background_summary}{manual_line}"
        self.progress.set(100)
        self.status.set(f"Image saved to: {result.output_file}. {background_summary}")
        messagebox.showinfo("Processing complete", message)

    def on_background_correction_cancelled(self) -> None:
        self.progress.set(0)
        self.status.set("Background correction cancelled. No image was saved.")

    def on_manual_alignment_cancelled(self) -> None:
        self.progress.set(0)
        self.status.set("Manual alignment cancelled. No image was saved.")

    def run_reduction(self) -> None:
        try:
            object_name = self.object_name.get().strip() or "object"
            paths = self._project_paths()
            alignment_mode = self.alignment_mode.get()
            background_correction = self.background_correction.get()

            self.set_progress(0)
            self.set_status("Processing bias, flats, alignment and RGB composition...")
            result = run_reduction(
                paths=paths,
                object_name=object_name,
                alignment_mode=alignment_mode,
                background_correction=BACKGROUND_OFF,
                progress_callback=self.update_progress,
                object_file_selection=self.selected_object_file_lists(),
            )

            result.background_correction = background_correction

            if alignment_mode == ALIGNMENT_MANUAL:
                self.after(0, self.open_manual_alignment, result)
                return

            if background_correction == BACKGROUND_OFF:
                self.after(0, self.save_final_image, result)
                return

            self.after(0, self.open_background_correction, result)
        except Exception as exc:
            self.set_progress(0)
            self.set_status("Processing failed.")
            self.show_error("Processing error", str(exc))


if __name__ == "__main__":
    app = ReductionApp()
    app.mainloop()
