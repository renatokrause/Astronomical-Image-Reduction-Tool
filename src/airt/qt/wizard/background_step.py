from __future__ import annotations

from pathlib import Path
import numpy as np

from PySide6.QtCore import Qt
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
    QSpinBox,
    QCheckBox,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
)

from airt.project import autosave_project
from airt.core.bands import sort_bands_recommended, normalize_band_name
from airt.core.color_mapping import build_color_mapping


class BackgroundPreviewView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)


class BackgroundStep(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard

        self.band_arrays: dict[str, np.ndarray] = {}
        self.preview_original: np.ndarray | None = None
        self.preview_corrected: np.ndarray | None = None
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

        title = QLabel("Background Correction")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Remove smooth background gradients for preview and final processed outputs. "
            "Original FITS files are never modified."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        root.addWidget(title)
        root.addWidget(subtitle)

        settings_card = QFrame()
        settings_card.setObjectName("contentCard")
        settings_layout = QGridLayout(settings_card)
        settings_layout.setContentsMargins(24, 20, 24, 24)
        settings_layout.setHorizontalSpacing(14)
        settings_layout.setVerticalSpacing(14)
        settings_layout.setColumnMinimumWidth(0, 160)
        settings_layout.setColumnStretch(1, 1)
        settings_layout.setColumnMinimumWidth(2, 160)
        settings_layout.setColumnStretch(3, 1)

        settings_title = QLabel("Correction settings")
        settings_title.setObjectName("sectionTitle")

        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(True)
        self.enabled_check.stateChanged.connect(self.on_enabled_changed)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Conservative", "conservative")
        self.mode_combo.addItem("Standard", "standard")
        self.mode_combo.addItem("Custom", "custom")
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)

        self.apply_to_combo = QComboBox()
        self.apply_to_combo.addItem("Per band", "per_band")
        self.apply_to_combo.addItem("RGB preview", "rgb_preview")
        self.apply_to_combo.currentIndexChanged.connect(self.on_settings_changed)

        self.protection_combo = QComboBox()
        self.protection_combo.addItem("Low", "low")
        self.protection_combo.addItem("Medium", "medium")
        self.protection_combo.addItem("High", "high")
        self.protection_combo.currentIndexChanged.connect(self.on_settings_changed)

        self.view_combo = QComboBox()
        self.view_combo.addItem("Original", "original")
        self.view_combo.addItem("Corrected", "corrected")
        self.view_combo.addItem("Difference", "difference")
        self.view_combo.currentIndexChanged.connect(self.update_preview)

        self.strength_spin = QDoubleSpinBox()
        self.strength_spin.setRange(0.0, 1.0)
        self.strength_spin.setDecimals(2)
        self.strength_spin.setSingleStep(0.05)
        self.strength_spin.valueChanged.connect(self.on_settings_changed)

        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(16, 512)
        self.scale_spin.setSingleStep(16)
        self.scale_spin.valueChanged.connect(self.on_settings_changed)

        settings_layout.addWidget(settings_title, 0, 0, 1, 4)
        settings_layout.addWidget(self.enabled_check, 1, 0, 1, 4)

        settings_layout.addWidget(QLabel("Mode"), 2, 0)
        settings_layout.addWidget(self.mode_combo, 2, 1)

        settings_layout.addWidget(QLabel("Apply to"), 2, 2)
        settings_layout.addWidget(self.apply_to_combo, 2, 3)

        settings_layout.addWidget(QLabel("Object protection"), 3, 0)
        settings_layout.addWidget(self.protection_combo, 3, 1)

        settings_layout.addWidget(QLabel("Preview"), 3, 2)
        settings_layout.addWidget(self.view_combo, 3, 3)

        settings_layout.addWidget(QLabel("Strength"), 4, 0)
        settings_layout.addWidget(self.strength_spin, 4, 1)

        settings_layout.addWidget(QLabel("Background scale"), 4, 2)
        settings_layout.addWidget(self.scale_spin, 4, 3)

        root.addWidget(settings_card)

        actions_card = QFrame()
        actions_card.setObjectName("contentCard")
        actions_layout = QHBoxLayout(actions_card)
        actions_layout.setContentsMargins(18, 14, 18, 14)
        actions_layout.setSpacing(10)

        actions_title = QLabel("Actions")
        actions_title.setObjectName("sectionTitle")

        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_settings)

        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self.fit_preview)

        self.zoom_in_button = QPushButton("Zoom in")
        self.zoom_in_button.clicked.connect(lambda: self.preview_view.scale(1.25, 1.25))

        self.zoom_out_button = QPushButton("Zoom out")
        self.zoom_out_button.clicked.connect(lambda: self.preview_view.scale(0.8, 0.8))

        actions_layout.addWidget(actions_title)
        actions_layout.addStretch(1)
        actions_layout.addWidget(self.reset_button)
        actions_layout.addSpacing(12)
        actions_layout.addWidget(self.fit_button)
        actions_layout.addWidget(self.zoom_in_button)
        actions_layout.addWidget(self.zoom_out_button)

        root.addWidget(actions_card)

        preview_card = QFrame()
        preview_card.setObjectName("contentCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(18, 18, 18, 18)
        preview_layout.setSpacing(10)

        self.preview_info = QLabel("Background correction preview will appear here.")
        self.preview_info.setObjectName("mutedText")
        self.preview_info.setWordWrap(True)

        self.preview_scene = QGraphicsScene(self)
        self.preview_view = BackgroundPreviewView()
        self.preview_view.setScene(self.preview_scene)
        self.preview_view.setBackgroundBrush(Qt.black)
        self.preview_view.setMinimumHeight(620)

        preview_layout.addWidget(self.preview_info)
        preview_layout.addWidget(self.preview_view, 1)

        root.addWidget(preview_card, 1)

        info = QFrame()
        info.setObjectName("infoCard")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(20, 14, 20, 14)

        self.info_text = QLabel(
            "Use Difference view to inspect what is being removed. If real nebula, galaxy arms, or halos appear strongly in Difference, use a more conservative correction."
        )
        self.info_text.setObjectName("infoText")
        self.info_text.setWordWrap(True)

        info_layout.addWidget(self.info_text)
        root.addWidget(info)

        outer.addWidget(scroll)

    def on_enter(self):
        self.wizard.footer.back_button.setEnabled(True)
        self.wizard.footer.next_button.setEnabled(True)
        self.wizard.footer.set_status("Configure background correction.")

        self.load_preview_data()
        self.load_settings_from_project()
        self.recompute_preview()

    def on_leave(self, target_index: int):
        self.persist_settings()

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
        saved = {}

        if project:
            saved = project.output_options.get("background_correction", {}) or {}

        default_enabled = bool(saved.get("enabled", True))
        default_mode = saved.get("mode", self.default_mode_from_preset())
        default_apply_to = saved.get("apply_to", "per_band")
        default_protection = saved.get("object_protection", self.default_protection_from_preset())
        default_strength = float(saved.get("strength", self.default_strength(default_mode)))
        default_scale = int(saved.get("scale", self.default_scale(default_mode)))

        self._loading_controls = True

        self.enabled_check.setChecked(default_enabled)
        self.set_combo_by_data(self.mode_combo, default_mode)
        self.set_combo_by_data(self.apply_to_combo, default_apply_to)
        self.set_combo_by_data(self.protection_combo, default_protection)
        self.set_combo_by_data(self.view_combo, saved.get("preview", "corrected"))

        self.strength_spin.setValue(default_strength)
        self.scale_spin.setValue(default_scale)

        self._loading_controls = False

        self.update_control_enabled_state()

    def set_combo_by_data(self, combo: QComboBox, value: str):
        index = combo.findData(value)

        if index >= 0:
            combo.setCurrentIndex(index)

    def default_mode_from_preset(self) -> str:
        project = self.wizard.project

        if not project:
            return "conservative"

        preset = getattr(project, "preset", "auto") or "auto"

        if preset in {"nebula", "extended_galaxy"}:
            return "conservative"

        if preset in {"compact_galaxy", "star_field", "auto"}:
            return "standard"

        return "conservative"

    def default_protection_from_preset(self) -> str:
        project = self.wizard.project

        if not project:
            return "medium"

        preset = getattr(project, "preset", "auto") or "auto"

        if preset in {"nebula", "extended_galaxy"}:
            return "high"

        return "medium"

    def default_strength(self, mode: str) -> float:
        if mode == "conservative":
            return 0.35

        if mode == "standard":
            return 0.60

        return 0.35

    def default_scale(self, mode: str) -> int:
        if mode == "conservative":
            return 160

        if mode == "standard":
            return 112

        return 128

    def on_enabled_changed(self):
        if self._loading_controls:
            return

        self.update_control_enabled_state()
        self.recompute_preview()
        self.persist_settings()

    def on_mode_changed(self):
        if self._loading_controls:
            return

        mode = self.mode_combo.currentData() or "conservative"

        self._loading_controls = True

        if mode != "custom":
            self.strength_spin.setValue(self.default_strength(mode))
            self.scale_spin.setValue(self.default_scale(mode))

        self._loading_controls = False

        self.update_control_enabled_state()
        self.recompute_preview()
        self.persist_settings()

    def update_control_enabled_state(self):
        enabled = self.enabled_check.isChecked()
        mode = self.mode_combo.currentData() or "conservative"
        custom = enabled and mode == "custom"

        self.mode_combo.setEnabled(enabled)
        self.apply_to_combo.setEnabled(enabled)
        self.protection_combo.setEnabled(enabled)
        self.strength_spin.setEnabled(custom)
        self.scale_spin.setEnabled(custom)

    def on_settings_changed(self):
        if self._loading_controls:
            return

        self.recompute_preview()
        self.persist_settings()

    def reset_settings(self):
        mode = self.default_mode_from_preset()

        self._loading_controls = True

        self.enabled_check.setChecked(True)
        self.set_combo_by_data(self.mode_combo, mode)
        self.set_combo_by_data(self.apply_to_combo, "per_band")
        self.set_combo_by_data(self.protection_combo, self.default_protection_from_preset())
        self.set_combo_by_data(self.view_combo, "corrected")
        self.strength_spin.setValue(self.default_strength(mode))
        self.scale_spin.setValue(self.default_scale(mode))

        self._loading_controls = False

        self.update_control_enabled_state()
        self.recompute_preview()
        self.persist_settings()

    def alignment_offsets(self) -> dict[str, dict[str, float]]:
        project = self.wizard.project

        if not project:
            return {}

        settings = project.output_options.get("alignment_settings", {}) or {}
        return settings.get("manual_offsets", {}) or getattr(project, "manual_offsets", {}) or {}

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

    def color_mapping_for_bands(self) -> dict[str, dict[str, str]]:
        project = self.wizard.project
        bands = sort_bands_recommended(self.band_arrays.keys())

        saved_mapping = {}
        mode = "photometric"
        custom_mapping = {}

        if project:
            saved_mapping = project.output_options.get("color_mapping", {}) or {}
            mode = project.output_options.get("color_mapping_mode", "photometric") or "photometric"
            custom_mapping = project.output_options.get("custom_color_mapping", {}) or {}

        if not saved_mapping:
            generated = build_color_mapping(
                bands=bands,
                mode=mode,
                saved_custom=custom_mapping,
            )
            saved_mapping = {
                item.band: {
                    "hex_color": item.hex_color,
                    "normalized_band": item.normalized_band,
                    "channel": item.channel,
                    "color_name": item.color_name,
                }
                for item in generated
            }

        result = {}

        for band in bands:
            normalized = normalize_band_name(band)

            direct = saved_mapping.get(band, {})
            normalized_match = None

            for saved_band, saved_item in saved_mapping.items():
                if normalize_band_name(saved_band) == normalized:
                    normalized_match = saved_item
                    break

            item = direct or normalized_match or {}

            result[band] = {
                "hex_color": item.get("hex_color", "#808080"),
                "channel": item.get("channel", "-"),
            }

        return result

    def channel_to_rgb_weight(self, channel: str, hex_color: str) -> tuple[float, float, float]:
        channel = (channel or "-").upper().strip()

        if channel == "R":
            return (1.0, 0.0, 0.0)

        if channel == "G":
            return (0.0, 1.0, 0.0)

        if channel == "B":
            return (0.0, 0.0, 1.0)

        if channel == "R+G":
            return (1.0, 1.0, 0.0)

        if channel == "R+B":
            return (1.0, 0.0, 1.0)

        if channel == "G+B":
            return (0.0, 1.0, 1.0)

        if channel == "R+G+B":
            return (1.0, 1.0, 1.0)

        if channel == "L":
            return (0.0, 0.0, 0.0)

        return self.hex_to_rgb(hex_color)

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

    def composite_rgb(self) -> np.ndarray | None:
        if not self.band_arrays:
            return None

        shapes = {array.shape for array in self.band_arrays.values()}

        if len(shapes) != 1:
            return None

        height, width = next(iter(shapes))
        rgb = np.zeros((height, width, 3), dtype=np.float32)
        chroma_count = 0

        luminance = None

        mapping = self.color_mapping_for_bands()
        offsets = self.alignment_offsets()

        for band in sort_bands_recommended(self.band_arrays.keys()):
            image = self.band_arrays[band]

            offset = offsets.get(band, {})
            shifted = self.shifted_array(
                image,
                float(offset.get("x", 0.0)),
                float(offset.get("y", 0.0)),
            )

            item = mapping.get(band, {})
            hex_color = item.get("hex_color", "#808080")
            channel = item.get("channel", "-")

            normalized_band = normalize_band_name(band)

            if channel == "L" or normalized_band == "L":
                luminance = shifted if luminance is None else np.maximum(luminance, shifted)
                continue

            color = self.channel_to_rgb_weight(channel, hex_color)

            if color == (0.0, 0.0, 0.0):
                continue

            rgb[:, :, 0] += shifted * color[0]
            rgb[:, :, 1] += shifted * color[1]
            rgb[:, :, 2] += shifted * color[2]
            chroma_count += 1

        if chroma_count == 0:
            if luminance is None:
                return None

            gray = np.clip(luminance, 0, 1)
            return np.dstack([gray, gray, gray]).astype(np.float32, copy=False)

        max_value = float(np.nanmax(rgb)) if np.any(np.isfinite(rgb)) else 0.0

        if max_value > 0:
            rgb = rgb / max_value

        rgb = np.clip(rgb, 0, 1)

        if luminance is not None:
            luminance = np.clip(luminance, 0, 1)

            max_channel = np.max(rgb, axis=2, keepdims=True)
            hue = np.divide(
                rgb,
                np.maximum(max_channel, 1e-6),
                out=np.zeros_like(rgb),
                where=max_channel > 1e-6,
            )

            grayscale_l = np.dstack([luminance, luminance, luminance])
            rgb = np.where(max_channel > 1e-6, hue * luminance[:, :, None], grayscale_l)

        return np.clip(rgb, 0, 1)

    def protection_percentile(self) -> float:
        protection = self.protection_combo.currentData() or "medium"

        if protection == "low":
            return 90.0

        if protection == "high":
            return 70.0

        return 80.0

    def estimate_background_channel(self, channel: np.ndarray, block_size: int) -> np.ndarray:
        height, width = channel.shape
        block_size = max(8, int(block_size))

        pad_h = (block_size - height % block_size) % block_size
        pad_w = (block_size - width % block_size) % block_size

        padded = np.pad(
            channel,
            ((0, pad_h), (0, pad_w)),
            mode="edge",
        )

        threshold = np.percentile(padded, self.protection_percentile())
        protected = np.where(padded <= threshold, padded, np.nan)

        h2, w2 = padded.shape

        blocks = protected.reshape(
            h2 // block_size,
            block_size,
            w2 // block_size,
            block_size,
        )

        with np.errstate(all="ignore"):
            coarse = np.nanmedian(blocks, axis=(1, 3))

        if np.isnan(coarse).any():
            fallback = float(np.nanmedian(protected))

            if not np.isfinite(fallback):
                fallback = float(np.nanmedian(padded))

            coarse = np.where(np.isfinite(coarse), coarse, fallback)

        background = np.repeat(np.repeat(coarse, block_size, axis=0), block_size, axis=1)
        background = background[:height, :width]

        try:
            from scipy.ndimage import gaussian_filter

            sigma = max(1.0, block_size / 3.0)
            background = gaussian_filter(background, sigma=sigma)
        except Exception:
            pass

        return background.astype(np.float32, copy=False)

    def correct_background(self, rgb: np.ndarray) -> np.ndarray:
        if not self.enabled_check.isChecked():
            return rgb.copy()

        strength = float(self.strength_spin.value())
        scale = int(self.scale_spin.value())

        corrected = np.zeros_like(rgb, dtype=np.float32)

        for channel_index in range(3):
            channel = rgb[:, :, channel_index]
            background = self.estimate_background_channel(channel, scale)
            variation = background - float(np.nanmedian(background))
            corrected[:, :, channel_index] = channel - strength * variation

        corrected = np.clip(corrected, 0, 1)

        max_value = float(np.nanmax(corrected)) if np.any(np.isfinite(corrected)) else 0.0

        if max_value > 0:
            corrected = corrected / max_value

        return np.clip(corrected, 0, 1)

    def recompute_preview(self):
        original = self.composite_rgb()
        self.preview_original = original

        if original is None:
            self.preview_corrected = None
            self.update_preview()
            return

        self.preview_corrected = self.correct_background(original)
        self.update_preview()

    def preview_image_for_current_view(self) -> np.ndarray | None:
        view = self.view_combo.currentData() or "corrected"

        if self.preview_original is None:
            return None

        if view == "original":
            return self.preview_original

        if view == "difference":
            if self.preview_corrected is None:
                return None

            diff = np.abs(self.preview_original - self.preview_corrected)
            max_value = float(np.nanmax(diff)) if np.any(np.isfinite(diff)) else 0.0

            if max_value > 0:
                diff = diff / max_value

            return np.clip(diff, 0, 1)

        return self.preview_corrected if self.preview_corrected is not None else self.preview_original

    def update_preview(self):
        image = self.preview_image_for_current_view()

        if image is None:
            self.preview_scene.clear()
            self.current_pixmap_item = None
            self.preview_info.setText("No compatible selected object bands are available for background preview.")
            return

        qimage = self.rgb_to_qimage(image)
        pixmap = QPixmap.fromImage(qimage)

        self.preview_scene.clear()
        self.current_pixmap_item = self.preview_scene.addPixmap(pixmap)
        self.preview_scene.setSceneRect(self.current_pixmap_item.boundingRect())

        state = "Enabled" if self.enabled_check.isChecked() else "Disabled"
        mode = self.mode_combo.currentText()
        view = self.view_combo.currentText()
        protection = self.protection_combo.currentText()

        self.preview_info.setText(
            f"Background correction: {state} | Mode: {mode} | View: {view} | Protection: {protection} | "
            f"Bands: {', '.join(sort_bands_recommended(self.band_arrays.keys()))}"
        )

        self.fit_preview()

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

    def fit_preview(self):
        if not self.current_pixmap_item:
            return

        self.preview_view.resetTransform()
        self.preview_view.fitInView(self.current_pixmap_item, Qt.KeepAspectRatio)

    def save_to_project(self):
        project = self.wizard.ensure_project()

        settings = {
            "enabled": bool(self.enabled_check.isChecked()),
            "mode": self.mode_combo.currentData() or "conservative",
            "apply_to": self.apply_to_combo.currentData() or "per_band",
            "object_protection": self.protection_combo.currentData() or "medium",
            "preview": self.view_combo.currentData() or "corrected",
            "strength": float(self.strength_spin.value()),
            "scale": int(self.scale_spin.value()),
        }

        project.output_options["background_correction"] = settings
        project.background_mode = "disabled" if not settings["enabled"] else settings["mode"]
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

            self.wizard.footer.set_status("Background correction settings saved.")
        except Exception as exc:
            self.wizard.footer.set_status(f"Could not autosave background correction settings: {exc}")

    def on_next(self) -> bool:
        self.persist_settings()
        self.wizard.go_to_step(7)
        return False
