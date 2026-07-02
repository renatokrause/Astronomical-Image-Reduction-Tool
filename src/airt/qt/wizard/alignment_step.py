from __future__ import annotations

from pathlib import Path
import numpy as np

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QComboBox,
    QDoubleSpinBox,
    QMessageBox,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QTableWidget,
    QTableWidgetItem,
)

from airt.project import autosave_project
from airt.core.bands import band_display_label, sort_bands_recommended, normalize_band_name


class AlignmentPreviewView(QGraphicsView):
    bandDragged = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self._last_scene_pos = None

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._last_scene_pos = self.mapToScene(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._last_scene_pos is not None:
            current = self.mapToScene(event.position().toPoint())
            delta = current - self._last_scene_pos
            self._last_scene_pos = current
            self.bandDragged.emit(float(delta.x()), float(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._last_scene_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class AlignmentStep(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard

        self.band_arrays: dict[str, np.ndarray] = {}
        self.band_counts: dict[str, int] = {}
        self.band_offsets: dict[str, dict[str, float]] = {}
        self.current_pixmap_item: QGraphicsPixmapItem | None = None
        self._loading_controls = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("pageScroll")

        content = QWidget()
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(48, 42, 48, 42)
        root.setSpacing(22)

        title = QLabel("Alignment")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Visually align detected object bands. The preview uses the color mapping from the previous step. "
            "Offsets are saved as project metadata and do not alter the original FITS files."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        root.addWidget(title)
        root.addWidget(subtitle)

        control_card = QFrame()
        control_card.setObjectName("contentCard")
        control_grid = QGridLayout(control_card)
        control_grid.setContentsMargins(24, 20, 24, 24)
        control_grid.setHorizontalSpacing(14)
        control_grid.setVerticalSpacing(14)
        control_grid.setColumnMinimumWidth(0, 150)
        control_grid.setColumnStretch(1, 1)

        control_title = QLabel("Band adjustment")
        control_title.setObjectName("sectionTitle")

        self.reference_band_combo = QComboBox()
        self.reference_band_combo.currentIndexChanged.connect(self.on_reference_band_changed)

        self.adjust_band_combo = QComboBox()
        self.adjust_band_combo.currentIndexChanged.connect(self.on_adjust_band_changed)

        self.x_spin = QDoubleSpinBox()
        self.x_spin.setRange(-10000, 10000)
        self.x_spin.setDecimals(2)
        self.x_spin.setSingleStep(0.5)
        self.x_spin.valueChanged.connect(self.on_offset_spin_changed)

        self.y_spin = QDoubleSpinBox()
        self.y_spin.setRange(-10000, 10000)
        self.y_spin.setDecimals(2)
        self.y_spin.setSingleStep(0.5)
        self.y_spin.valueChanged.connect(self.on_offset_spin_changed)


        control_grid.addWidget(control_title, 0, 0, 1, 6)

        control_grid.addWidget(QLabel("Reference band"), 1, 0)
        control_grid.addWidget(self.reference_band_combo, 1, 1)

        control_grid.addWidget(QLabel("Band to adjust"), 1, 2)
        control_grid.addWidget(self.adjust_band_combo, 1, 3)


        control_grid.addWidget(QLabel("X offset"), 2, 0)
        control_grid.addWidget(self.x_spin, 2, 1)

        control_grid.addWidget(QLabel("Y offset"), 2, 2)
        control_grid.addWidget(self.y_spin, 2, 3)

        root.addWidget(control_card)

        preview_card = QFrame()
        preview_card.setObjectName("contentCard")
        preview_card_layout = QVBoxLayout(preview_card)
        preview_card_layout.setContentsMargins(18, 18, 18, 18)
        preview_card_layout.setSpacing(10)

        self.preview_info = QLabel("Alignment preview will appear here.")
        self.preview_info.setObjectName("mutedText")
        self.preview_info.setWordWrap(True)

        self.preview_scene = QGraphicsScene(self)
        self.preview_view = AlignmentPreviewView()
        self.preview_view.setScene(self.preview_scene)
        self.preview_view.setBackgroundBrush(Qt.black)
        self.preview_view.setMinimumHeight(620)
        self.preview_view.bandDragged.connect(self.move_current_band)

        preview_card_layout.addWidget(self.preview_info)
        preview_card_layout.addWidget(self.preview_view, 1)

        root.addWidget(preview_card, 1)

        actions_card = QFrame()
        actions_card.setObjectName("contentCard")
        actions_layout = QHBoxLayout(actions_card)
        actions_layout.setContentsMargins(18, 14, 18, 14)
        actions_layout.setSpacing(10)

        actions_title = QLabel("Actions")
        actions_title.setObjectName("sectionTitle")

        self.auto_button = QPushButton("Auto")
        self.auto_button.clicked.connect(self.auto_align)

        self.reset_band_button = QPushButton("Reset Band")
        self.reset_band_button.clicked.connect(self.reset_current_band)

        self.reset_all_button = QPushButton("Reset All")
        self.reset_all_button.clicked.connect(self.reset_all_bands)

        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self.fit_preview)

        self.zoom_in_button = QPushButton("Zoom in")
        self.zoom_in_button.clicked.connect(lambda: self.preview_view.scale(1.25, 1.25))

        self.zoom_out_button = QPushButton("Zoom out")
        self.zoom_out_button.clicked.connect(lambda: self.preview_view.scale(0.8, 0.8))

        actions_layout.addWidget(actions_title)
        actions_layout.addStretch(1)
        actions_layout.addWidget(self.auto_button)
        actions_layout.addWidget(self.reset_band_button)
        actions_layout.addWidget(self.reset_all_button)
        actions_layout.addSpacing(12)
        actions_layout.addWidget(self.fit_button)
        actions_layout.addWidget(self.zoom_in_button)
        actions_layout.addWidget(self.zoom_out_button)

        root.addWidget(actions_card)

        summary_card = QFrame()
        summary_card.setObjectName("contentCard")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(24, 20, 24, 24)
        summary_layout.setSpacing(10)

        summary_title = QLabel("Band summary")
        summary_title.setObjectName("sectionTitle")

        self.summary_table = QTableWidget(0, 4)
        self.summary_table.setHorizontalHeaderLabels(["Band", "Frames", "X", "Y"])
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setMinimumHeight(190)
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.horizontalHeader().setStretchLastSection(True)

        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(self.summary_table)

        root.addWidget(summary_card)

        info = QFrame()
        info.setObjectName("infoCard")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(20, 14, 20, 14)

        self.info_text = QLabel(
            "Keyboard shortcuts: arrow keys move the selected band. You can also drag the preview image with the mouse to move the selected band. Reset All leaves all band offsets at zero."
        )
        self.info_text.setObjectName("infoText")
        self.info_text.setWordWrap(True)

        info_layout.addWidget(self.info_text)
        root.addWidget(info)

        outer.addWidget(scroll)

        self.setFocusPolicy(Qt.StrongFocus)

    def on_enter(self):
        self.wizard.footer.back_button.setEnabled(True)
        self.wizard.footer.next_button.setEnabled(True)
        self.wizard.footer.set_status("Adjust visual band alignment.")
        self.setFocus()

        self.load_preview_data()
        self.load_settings_from_project()
        self.populate_controls()
        self.update_preview(preserve_view=False)

    def on_leave(self, target_index: int):
        self.persist_settings()

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key_Left:
            self.move_current_band(-self.step_size(), 0)
            return
        if key == Qt.Key_Right:
            self.move_current_band(self.step_size(), 0)
            return
        if key == Qt.Key_Up:
            self.move_current_band(0, -self.step_size())
            return
        if key == Qt.Key_Down:
            self.move_current_band(0, self.step_size())
            return

        super().keyPressEvent(event)

    def step_size(self) -> float:
        return 1.0

    def selected_object_files_by_band(self) -> dict[str, list[str]]:
        project = self.wizard.project
        if not project:
            return {}

        return {
            band: list(paths)
            for band, paths in getattr(project, "selected_object_files", {}).items()
            if band and band != "-" and paths
        }

    def load_preview_data(self):
        self.band_arrays = {}
        self.band_counts = {}

        selected = self.selected_object_files_by_band()

        for band in sort_bands_recommended(selected.keys()):
            paths = selected[band]
            arrays = []

            for path_text in paths:
                path = Path(path_text)
                if not path.exists():
                    continue

                try:
                    arrays.append(self.load_fits_array(path))
                except Exception:
                    continue

            if not arrays:
                continue

            reference_shape = arrays[0].shape
            arrays = [array for array in arrays if array.shape == reference_shape]

            if not arrays:
                continue

            combined = arrays[0] if len(arrays) == 1 else np.nanmedian(np.stack(arrays, axis=0), axis=0)

            self.band_arrays[band] = self.normalize_array(combined)
            self.band_counts[band] = len(arrays)

    def load_fits_array(self, path: Path) -> np.ndarray:
        from astropy.io import fits

        data = fits.getdata(path, 0)
        data = np.asarray(data)

        if data.ndim > 2:
            data = np.squeeze(data)

            if data.ndim > 2:
                data = data[0]

        if data.ndim != 2:
            raise ValueError(f"Unsupported FITS dimensions: {data.shape}")

        return data.astype(np.float32, copy=False)

    def normalize_array(self, data: np.ndarray) -> np.ndarray:
        finite = np.isfinite(data)
        if not np.any(finite):
            return np.zeros_like(data, dtype=np.float32)

        valid = data[finite]
        low, high = np.percentile(valid, [1, 99.5])

        if high <= low:
            low = float(np.min(valid))
            high = float(np.max(valid))

        if high <= low:
            high = low + 1.0

        stretched = (data - low) / (high - low)
        stretched = np.clip(stretched, 0, 1)
        stretched[~finite] = 0

        return stretched.astype(np.float32, copy=False)

    def load_settings_from_project(self):
        project = self.wizard.project
        self.band_offsets = {}

        for band in self.band_arrays:
            self.band_offsets[band] = {"x": 0.0, "y": 0.0}

        if not project:
            return

        settings = project.output_options.get("alignment_settings", {})
        saved_offsets = settings.get("manual_offsets", {}) or getattr(project, "manual_offsets", {}) or {}

        for band in self.band_arrays:
            value = saved_offsets.get(band, {})
            self.band_offsets[band] = {
                "x": float(value.get("x", 0.0)),
                "y": float(value.get("y", 0.0)),
            }

    def populate_controls(self):
        bands = sort_bands_recommended(self.band_arrays.keys())

        self._loading_controls = True

        current_reference = self.reference_band_combo.currentData()
        current_adjust = self.adjust_band_combo.currentData()

        self.reference_band_combo.clear()
        self.adjust_band_combo.clear()

        for band in bands:
            self.reference_band_combo.addItem(self.display_band(band), band)
            self.adjust_band_combo.addItem(self.display_band(band), band)

        reference_band = self.preferred_reference_band(bands)

        if current_reference in bands:
            reference_band = current_reference

        project = self.wizard.project
        if project:
            saved_reference = project.output_options.get("alignment_settings", {}).get("reference_band", "")
            if saved_reference in bands:
                reference_band = saved_reference

        reference_index = self.reference_band_combo.findData(reference_band)
        if reference_index >= 0:
            self.reference_band_combo.setCurrentIndex(reference_index)

        if current_adjust in bands:
            adjust_band = current_adjust
        elif bands:
            adjust_band = bands[0]
        else:
            adjust_band = ""

        adjust_index = self.adjust_band_combo.findData(adjust_band)
        if adjust_index >= 0:
            self.adjust_band_combo.setCurrentIndex(adjust_index)

        self._loading_controls = False

        self.update_offset_spins()
        self.populate_summary()

    def preferred_reference_band(self, bands: list[str]) -> str:
        if not bands:
            return ""

        normalized_map = {normalize_band_name(band): band for band in bands}

        for candidate in ["L", "V", "G", "R", "B"]:
            if candidate in normalized_map:
                return normalized_map[candidate]

        return bands[0]

    def display_band(self, band: str) -> str:
        return band_display_label(band)

    def current_reference_band(self) -> str:
        return self.reference_band_combo.currentData() or ""

    def current_adjust_band(self) -> str:
        return self.adjust_band_combo.currentData() or ""

    def on_reference_band_changed(self):
        if self._loading_controls:
            return

        reference = self.current_reference_band()
        if reference:
            self.band_offsets.setdefault(reference, {"x": 0.0, "y": 0.0})
            self.band_offsets[reference] = {"x": 0.0, "y": 0.0}

        self.update_offset_spins()
        self.populate_summary()
        self.update_preview(preserve_view=True)
        self.persist_settings()

    def on_adjust_band_changed(self):
        if self._loading_controls:
            return

        self.update_offset_spins()
        self.setFocus()

    def update_offset_spins(self):
        band = self.current_adjust_band()

        self._loading_controls = True

        if not band:
            self.x_spin.setValue(0.0)
            self.y_spin.setValue(0.0)
        else:
            offsets = self.band_offsets.setdefault(band, {"x": 0.0, "y": 0.0})
            self.x_spin.setValue(float(offsets.get("x", 0.0)))
            self.y_spin.setValue(float(offsets.get("y", 0.0)))

        self._loading_controls = False

    def on_offset_spin_changed(self):
        if self._loading_controls:
            return

        band = self.current_adjust_band()
        if not band:
            return

        if band == self.current_reference_band():
            self._loading_controls = True
            self.x_spin.setValue(0.0)
            self.y_spin.setValue(0.0)
            self._loading_controls = False
            self.band_offsets[band] = {"x": 0.0, "y": 0.0}
        else:
            self.band_offsets[band] = {
                "x": float(self.x_spin.value()),
                "y": float(self.y_spin.value()),
            }

        self.populate_summary()
        self.update_preview(preserve_view=True)
        self.persist_settings()

    def move_current_band(self, dx: float, dy: float):
        band = self.current_adjust_band()

        if not band:
            return

        if band == self.current_reference_band():
            self.info_text.setText("The reference band remains fixed at X=0, Y=0.")
            return

        offsets = self.band_offsets.setdefault(band, {"x": 0.0, "y": 0.0})
        offsets["x"] = float(offsets.get("x", 0.0)) + dx
        offsets["y"] = float(offsets.get("y", 0.0)) + dy

        self.update_offset_spins()
        self.populate_summary()
        self.update_preview(preserve_view=True)
        self.persist_settings()
        self.setFocus()

    def reset_current_band(self):
        band = self.current_adjust_band()
        if not band:
            return

        self.band_offsets[band] = {"x": 0.0, "y": 0.0}

        self.update_offset_spins()
        self.populate_summary()
        self.update_preview(preserve_view=True)
        self.persist_settings()

    def reset_all_bands(self):
        for band in self.band_offsets:
            self.band_offsets[band] = {"x": 0.0, "y": 0.0}

        self.update_offset_spins()
        self.populate_summary()
        self.update_preview(preserve_view=True)
        self.persist_settings()

    def estimate_shift_fft(self, reference: np.ndarray, moving: np.ndarray) -> tuple[float, float]:
        ref = reference.astype(np.float32, copy=False)
        mov = moving.astype(np.float32, copy=False)

        ref = ref - float(np.nanmean(ref))
        mov = mov - float(np.nanmean(mov))

        ref[~np.isfinite(ref)] = 0
        mov[~np.isfinite(mov)] = 0

        ref_fft = np.fft.fft2(ref)
        mov_fft = np.fft.fft2(mov)

        cross_power = ref_fft * np.conj(mov_fft)
        denominator = np.abs(cross_power)
        denominator[denominator == 0] = 1e-12
        cross_power = cross_power / denominator

        correlation = np.fft.ifft2(cross_power).real
        max_position = np.unravel_index(np.argmax(correlation), correlation.shape)

        shifts = np.array(max_position, dtype=np.float64)
        shape = np.array(reference.shape, dtype=np.float64)
        midpoint = np.fix(shape / 2)

        shifts[shifts > midpoint] -= shape[shifts > midpoint]

        y_shift = float(shifts[0])
        x_shift = float(shifts[1])

        return x_shift, y_shift

    def auto_align(self):
        reference_band = self.current_reference_band()

        if not reference_band or reference_band not in self.band_arrays:
            QMessageBox.information(self, "No reference band", "Select a valid reference band first.")
            return

        reference = self.band_arrays[reference_band]

        for band, image in self.band_arrays.items():
            if band == reference_band:
                self.band_offsets[band] = {"x": 0.0, "y": 0.0}
                continue

            if image.shape != reference.shape:
                continue

            try:
                try:
                    from skimage.registration import phase_cross_correlation

                    shift, error, _ = phase_cross_correlation(
                        reference,
                        image,
                        upsample_factor=10,
                    )

                    x_shift = float(shift[1])
                    y_shift = float(shift[0])
                except Exception:
                    x_shift, y_shift = self.estimate_shift_fft(reference, image)

                self.band_offsets[band] = {
                    "x": x_shift,
                    "y": y_shift,
                }
            except Exception:
                continue

        self.update_offset_spins()
        self.populate_summary()
        self.update_preview(preserve_view=True)
        self.persist_settings()
        self.wizard.footer.set_status("Automatic band alignment offsets estimated.")

    def color_mapping_for_bands(self) -> dict[str, str]:
        project = self.wizard.project
        if not project:
            return {}

        mapping = project.output_options.get("color_mapping", {}) or {}
        return {band: mapping.get(band, {}).get("hex_color", "#808080") for band in self.band_arrays}

    def hex_to_rgb(self, hex_color: str) -> tuple[float, float, float]:
        value = (hex_color or "#808080").strip().lstrip("#")

        try:
            return (
                int(value[0:2], 16) / 255.0,
                int(value[2:4], 16) / 255.0,
                int(value[4:6], 16) / 255.0,
            )
        except Exception:
            return (0.5, 0.5, 0.5)

    def shifted_array(self, image: np.ndarray, x: float, y: float) -> np.ndarray:
        try:
            from scipy.ndimage import shift

            return shift(
                image,
                shift=(y, x),
                order=1,
                mode="constant",
                cval=0.0,
                prefilter=False,
            ).astype(np.float32, copy=False)
        except Exception:
            return np.roll(image, shift=(int(round(y)), int(round(x))), axis=(0, 1))

    def composite_rgb(self) -> np.ndarray | None:
        if not self.band_arrays:
            return None

        shapes = {array.shape for array in self.band_arrays.values()}
        if len(shapes) != 1:
            return None

        height, width = next(iter(shapes))
        rgb = np.zeros((height, width, 3), dtype=np.float32)
        colors = self.color_mapping_for_bands()

        for band in sort_bands_recommended(self.band_arrays.keys()):
            image = self.band_arrays[band]
            offsets = self.band_offsets.setdefault(band, {"x": 0.0, "y": 0.0})
            shifted = self.shifted_array(
                image,
                float(offsets.get("x", 0.0)),
                float(offsets.get("y", 0.0)),
            )

            color = self.hex_to_rgb(colors.get(band, "#808080"))

            rgb[:, :, 0] += shifted * color[0]
            rgb[:, :, 1] += shifted * color[1]
            rgb[:, :, 2] += shifted * color[2]

        max_value = float(np.nanmax(rgb)) if np.any(np.isfinite(rgb)) else 0.0
        if max_value > 0:
            rgb = rgb / max_value

        return np.clip(rgb, 0, 1)

    def rgb_to_qimage(self, rgb: np.ndarray) -> QImage:
        image8 = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
        image8 = np.ascontiguousarray(image8)

        height, width, channels = image8.shape
        bytes_per_line = image8.strides[0]

        return QImage(
            image8.data,
            width,
            height,
            bytes_per_line,
            QImage.Format_RGB888,
        ).copy()

    def update_preview(self, preserve_view: bool = False):
        old_transform = self.preview_view.transform()
        old_h_scroll = self.preview_view.horizontalScrollBar().value()
        old_v_scroll = self.preview_view.verticalScrollBar().value()

        rgb = self.composite_rgb()

        if rgb is None:
            self.preview_scene.clear()
            self.current_pixmap_item = None
            self.preview_info.setText(
                "No compatible selected object bands are available for alignment preview."
            )
            return

        qimage = self.rgb_to_qimage(rgb)
        pixmap = QPixmap.fromImage(qimage)

        self.preview_scene.clear()
        self.current_pixmap_item = self.preview_scene.addPixmap(pixmap)
        self.preview_scene.setSceneRect(self.current_pixmap_item.boundingRect())

        reference = self.current_reference_band() or "-"
        adjusted = self.current_adjust_band() or "-"

        self.preview_info.setText(
            f"Reference band: {self.display_band(reference)} | "
            f"Band to adjust: {self.display_band(adjusted)} | "
            f"Bands in preview: {', '.join(self.display_band(band) for band in sort_bands_recommended(self.band_arrays))}"
        )

        if preserve_view:
            self.preview_view.setTransform(old_transform)
            self.preview_view.horizontalScrollBar().setValue(old_h_scroll)
            self.preview_view.verticalScrollBar().setValue(old_v_scroll)
        else:
            self.fit_preview()

    def fit_preview(self):
        if not self.current_pixmap_item:
            return

        self.preview_view.resetTransform()
        self.preview_view.fitInView(self.current_pixmap_item, Qt.KeepAspectRatio)

    def populate_summary(self):
        bands = sort_bands_recommended(self.band_arrays.keys())
        self.summary_table.setRowCount(len(bands))

        reference = self.current_reference_band()

        for row, band in enumerate(bands):
            offsets = self.band_offsets.setdefault(band, {"x": 0.0, "y": 0.0})

            values = [
                self.display_band(band) + ("  [reference]" if band == reference else ""),
                str(self.band_counts.get(band, 0)),
                f"{float(offsets.get('x', 0.0)):.2f}",
                f"{float(offsets.get('y', 0.0)):.2f}",
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                self.summary_table.setItem(row, column, item)

            self.summary_table.setRowHeight(row, 32)

        self.summary_table.resizeColumnsToContents()

    def save_to_project(self):
        project = self.wizard.ensure_project()

        reference_band = self.current_reference_band()

        project.alignment_mode = "visual_offsets"
        project.manual_offsets = {
            band: {
                "x": float(offsets.get("x", 0.0)),
                "y": float(offsets.get("y", 0.0)),
            }
            for band, offsets in self.band_offsets.items()
        }

        project.output_options["alignment_settings"] = {
            "mode": "visual_offsets",
            "reference_band": reference_band,
            "manual_offsets": project.manual_offsets,
        }

        project.update_timestamp()

    def persist_settings(self):
        self.save_to_project()

        project = self.wizard.project
        if not project or not project.project_file:
            return

        try:
            autosave_project(project)
            if hasattr(self.wizard, "mark_project_recent"):
                self.wizard.mark_project_recent()
            self.wizard.footer.set_status("Alignment settings saved.")
        except Exception as exc:
            self.wizard.footer.set_status(f"Could not autosave alignment settings: {exc}")

    def on_next(self) -> bool:
        self.persist_settings()
        self.wizard.go_to_step(6)
        return False
