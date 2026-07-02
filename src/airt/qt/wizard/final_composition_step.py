from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
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
    QLineEdit,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
)

from airt.project import autosave_project
from airt.core.final_render import build_final_image, rgb_to_qimage, output_folder_for_project, object_name_for_project


class CompositionPreviewView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)


class FinalCompositionStep(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
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

        title = QLabel("Final Composition & Export")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Choose final rendering parameters and output formats. Files are generated on the next step."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        root.addWidget(title)
        root.addWidget(subtitle)

        composition_card = QFrame()
        composition_card.setObjectName("contentCard")
        composition_layout = QGridLayout(composition_card)
        composition_layout.setContentsMargins(24, 20, 24, 24)
        composition_layout.setHorizontalSpacing(14)
        composition_layout.setVerticalSpacing(14)
        composition_layout.setColumnMinimumWidth(0, 150)
        composition_layout.setColumnStretch(1, 1)
        composition_layout.setColumnMinimumWidth(2, 150)
        composition_layout.setColumnStretch(3, 1)

        composition_title = QLabel("Composition")
        composition_title.setObjectName("sectionTitle")

        self.rendering_combo = QComboBox()
        self.rendering_combo.addItem("Grayscale", "grayscale")
        self.rendering_combo.addItem("Color", "color")
        self.rendering_combo.currentIndexChanged.connect(self.on_settings_changed)

        self.stretch_combo = QComboBox()
        self.stretch_combo.addItem("Linear", "linear")
        self.stretch_combo.addItem("Auto", "auto")
        self.stretch_combo.addItem("Soft", "soft")
        self.stretch_combo.addItem("Strong", "strong")
        self.stretch_combo.currentIndexChanged.connect(self.on_settings_changed)

        self.saturation_spin = QDoubleSpinBox()
        self.saturation_spin.setRange(0.0, 3.0)
        self.saturation_spin.setDecimals(2)
        self.saturation_spin.setSingleStep(0.10)
        self.saturation_spin.valueChanged.connect(self.on_settings_changed)

        self.brightness_spin = QDoubleSpinBox()
        self.brightness_spin.setRange(-1.0, 1.0)
        self.brightness_spin.setDecimals(2)
        self.brightness_spin.setSingleStep(0.05)
        self.brightness_spin.valueChanged.connect(self.on_settings_changed)

        self.contrast_spin = QDoubleSpinBox()
        self.contrast_spin.setRange(0.25, 3.0)
        self.contrast_spin.setDecimals(2)
        self.contrast_spin.setSingleStep(0.10)
        self.contrast_spin.valueChanged.connect(self.on_settings_changed)

        composition_layout.addWidget(composition_title, 0, 0, 1, 4)
        composition_layout.addWidget(QLabel("Rendering"), 1, 0)
        composition_layout.addWidget(self.rendering_combo, 1, 1)
        composition_layout.addWidget(QLabel("Stretch"), 1, 2)
        composition_layout.addWidget(self.stretch_combo, 1, 3)
        composition_layout.addWidget(QLabel("Saturation"), 2, 0)
        composition_layout.addWidget(self.saturation_spin, 2, 1)
        composition_layout.addWidget(QLabel("Brightness"), 2, 2)
        composition_layout.addWidget(self.brightness_spin, 2, 3)
        composition_layout.addWidget(QLabel("Contrast"), 3, 0)
        composition_layout.addWidget(self.contrast_spin, 3, 1)

        self.reset_composition_button = QPushButton("Reset")
        self.reset_composition_button.clicked.connect(self.reset_settings)
        composition_layout.addWidget(self.reset_composition_button, 3, 3)

        root.addWidget(composition_card)

        export_card = QFrame()
        export_card.setObjectName("contentCard")
        export_layout = QGridLayout(export_card)
        export_layout.setContentsMargins(24, 20, 24, 24)
        export_layout.setHorizontalSpacing(14)
        export_layout.setVerticalSpacing(14)
        export_layout.setColumnMinimumWidth(0, 150)
        export_layout.setColumnStretch(1, 1)

        export_title = QLabel("Export")
        export_title.setObjectName("sectionTitle")

        self.file_base_name_edit = QLineEdit()
        self.output_folder_label = QLabel("")
        self.output_folder_label.setObjectName("mutedText")
        self.output_folder_label.setWordWrap(True)

        self.png_check = QCheckBox("PNG")
        self.tiff_check = QCheckBox("TIFF")
        self.fits_check = QCheckBox("FITS")
        self.jpeg_check = QCheckBox("JPEG")
        self.open_folder_check = QCheckBox("Open output folder after processing")

        for checkbox in [
            self.png_check,
            self.tiff_check,
            self.fits_check,
            self.jpeg_check,
            self.open_folder_check,
        ]:
            checkbox.stateChanged.connect(self.on_settings_changed)

        self.jpeg_quality_spin = QSpinBox()
        self.jpeg_quality_spin.setRange(50, 100)
        self.jpeg_quality_spin.setSingleStep(5)
        self.jpeg_quality_spin.valueChanged.connect(self.on_settings_changed)

        export_layout.addWidget(export_title, 0, 0, 1, 4)
        export_layout.addWidget(QLabel("File base name"), 1, 0)
        export_layout.addWidget(self.file_base_name_edit, 1, 1, 1, 3)
        export_layout.addWidget(QLabel("Output folder"), 2, 0)
        export_layout.addWidget(self.output_folder_label, 2, 1, 1, 3)
        export_layout.addWidget(self.png_check, 3, 0)
        export_layout.addWidget(self.tiff_check, 3, 1)
        export_layout.addWidget(self.fits_check, 3, 2)
        export_layout.addWidget(self.jpeg_check, 3, 3)
        export_layout.addWidget(QLabel("JPEG quality"), 4, 0)
        export_layout.addWidget(self.jpeg_quality_spin, 4, 1)
        export_layout.addWidget(self.open_folder_check, 5, 0, 1, 4)

        root.addWidget(export_card)

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

        actions_card.setVisible(False)
        root.addWidget(actions_card)

        preview_card = QFrame()
        preview_card.setObjectName("contentCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(18, 18, 18, 18)
        preview_layout.setSpacing(10)

        self.preview_info = QLabel("Final composition preview will appear here.")
        self.preview_info.setObjectName("mutedText")
        self.preview_info.setWordWrap(True)

        self.preview_scene = QGraphicsScene(self)
        self.preview_view = CompositionPreviewView()
        self.preview_view.setScene(self.preview_scene)
        self.preview_view.setBackgroundBrush(Qt.black)
        self.preview_view.setMinimumHeight(620)

        preview_layout.addWidget(self.preview_info)
        preview_layout.addWidget(self.preview_view, 1)

        preview_card.setVisible(False)
        root.addWidget(preview_card, 1)

        outer.addWidget(scroll)

    def on_enter(self):
        self.wizard.footer.back_button.setEnabled(True)
        self.wizard.footer.next_button.setEnabled(True)
        self.wizard.footer.set_status("Configure final composition and export.")

        self.load_settings_from_project()

    def on_leave(self, target_index: int):
        self.persist_settings()

    def set_combo_by_data(self, combo: QComboBox, value: str):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def load_settings_from_project(self):
        project = self.wizard.ensure_project()
        composition = project.output_options.get("final_composition", {})
        export = project.output_options.get("final_export", {})

        self._loading_controls = True

        self.set_combo_by_data(self.rendering_combo, composition.get("rendering", "color"))
        self.set_combo_by_data(self.stretch_combo, composition.get("stretch", "auto"))

        self.saturation_spin.setValue(float(composition.get("saturation", 1.0)))
        self.brightness_spin.setValue(float(composition.get("brightness", 0.0)))
        self.contrast_spin.setValue(float(composition.get("contrast", 1.0)))

        self.file_base_name_edit.setText(export.get("file_base_name", object_name_for_project(project)))
        self.output_folder_label.setText(str(output_folder_for_project(project)))

        formats = export.get("formats", {})
        self.png_check.setChecked(bool(formats.get("png", True)))
        self.tiff_check.setChecked(bool(formats.get("tiff", False)))
        self.fits_check.setChecked(bool(formats.get("fits", False)))
        self.jpeg_check.setChecked(bool(formats.get("jpeg", False)))
        self.jpeg_quality_spin.setValue(int(export.get("jpeg_quality", 95)))
        self.open_folder_check.setChecked(bool(export.get("open_output_folder", True)))

        self._loading_controls = False

    def current_composition_settings(self) -> dict:
        return {
            "rendering": self.rendering_combo.currentData() or "grayscale",
            "stretch": self.stretch_combo.currentData() or "auto",
            "saturation": float(self.saturation_spin.value()),
            "brightness": float(self.brightness_spin.value()),
            "contrast": float(self.contrast_spin.value()),
        }

    def current_export_settings(self) -> dict:
        return {
            "file_base_name": self.file_base_name_edit.text().strip() or object_name_for_project(self.wizard.project),
            "formats": {
                "png": bool(self.png_check.isChecked()),
                "tiff": bool(self.tiff_check.isChecked()),
                "fits": bool(self.fits_check.isChecked()),
                "jpeg": bool(self.jpeg_check.isChecked()),
            },
            "jpeg_quality": int(self.jpeg_quality_spin.value()),
            "open_output_folder": bool(self.open_folder_check.isChecked()),
        }

    def on_settings_changed(self):
        if self._loading_controls:
            return

        self.save_to_project()
        self.persist_settings()

    def reset_settings(self):
        self._loading_controls = True

        self.set_combo_by_data(self.rendering_combo, "color")
        self.set_combo_by_data(self.stretch_combo, "auto")
        self.saturation_spin.setValue(1.0)
        self.brightness_spin.setValue(0.0)
        self.contrast_spin.setValue(1.0)
        self.png_check.setChecked(True)
        self.tiff_check.setChecked(False)
        self.fits_check.setChecked(False)
        self.jpeg_check.setChecked(False)
        self.jpeg_quality_spin.setValue(95)
        self.open_folder_check.setChecked(True)

        self._loading_controls = False

        self.save_to_project()
        self.persist_settings()

    def recompute_preview(self):
        try:
            result = build_final_image(
                self.wizard.project,
                self.current_composition_settings(),
            )
        except Exception as exc:
            self.preview_scene.clear()
            self.current_pixmap_item = None
            self.preview_info.setText(f"Could not render final preview: {exc}")
            return

        qimage = rgb_to_qimage(result.image)
        pixmap = QPixmap.fromImage(qimage)

        self.preview_scene.clear()
        self.current_pixmap_item = self.preview_scene.addPixmap(pixmap)
        self.preview_scene.setSceneRect(self.current_pixmap_item.boundingRect())

        self.preview_info.setText(
            f"Rendering: {self.rendering_combo.currentText()} | "
            f"Stretch: {self.stretch_combo.currentText()} | "
            f"Bands: {', '.join(result.bands)}"
        )

        self.fit_preview()

    def fit_preview(self):
        if not self.current_pixmap_item:
            return

        self.preview_view.resetTransform()
        self.preview_view.fitInView(self.current_pixmap_item, Qt.KeepAspectRatio)

    def save_to_project(self):
        project = self.wizard.ensure_project()
        project.output_options["final_composition"] = self.current_composition_settings()
        project.output_options["final_export"] = self.current_export_settings()
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

            self.wizard.footer.set_status("Final composition and export settings saved.")
        except Exception as exc:
            self.wizard.footer.set_status(f"Could not autosave final settings: {exc}")

    def on_next(self) -> bool:
        self.persist_settings()
        self.wizard.go_to_step(8)
        return False
