from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QComboBox,
    QFrame,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QColorDialog,
    QLineEdit,
)

from airt.project import autosave_project
from airt.core.color_mapping import (
    BandColorMapping,
    build_color_mapping,
    is_valid_hex_color,
    mapping_to_project_dict,
)


PRESETS = {
    "auto": "Auto",
    "compact_galaxy": "Compact galaxy",
    "extended_galaxy": "Extended galaxy",
    "nebula": "Nebula",
    "star_field": "Star field / cluster",
    "manual_advanced": "Manual advanced",
}


COLOR_MAPPING_MODES = {
    "photometric": "Photometric",
    "chromatic_order": "Chromatic Order",
    "sho": "SHO",
    "hoo": "HOO",
    "custom": "Custom",
}


CHANNELS = [
    "-",
    "R",
    "G",
    "B",
    "R+G",
    "R+B",
    "G+B",
    "R+G+B",
    "L",
]


class PresetStep(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self.current_mapping: list[BandColorMapping] = []
        self._loading = False

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

        title = QLabel("Object preset and color mapping")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Choose the processing strategy and define how detected bands will be represented in preview and RGB composition. "
            "Color mapping is visualization metadata and does not alter the original scientific data."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        root.addWidget(title)
        root.addWidget(subtitle)

        settings_card = QFrame()
        settings_card.setObjectName("contentCard")
        settings_layout = QGridLayout(settings_card)
        settings_layout.setContentsMargins(28, 24, 28, 28)
        settings_layout.setHorizontalSpacing(16)
        settings_layout.setVerticalSpacing(16)
        settings_layout.setColumnMinimumWidth(0, 180)
        settings_layout.setColumnStretch(1, 1)

        section = QLabel("Processing and visualization")
        section.setObjectName("sectionTitle")
        settings_layout.addWidget(section, 0, 0, 1, 2)

        preset_label = QLabel("Object type")
        preset_label.setObjectName("fieldLabel")

        self.preset_combo = QComboBox()
        for key, label in PRESETS.items():
            self.preset_combo.addItem(label, key)

        color_mode_label = QLabel("Color Mapping")
        color_mode_label.setObjectName("fieldLabel")

        self.color_mapping_combo = QComboBox()
        for key, label in COLOR_MAPPING_MODES.items():
            self.color_mapping_combo.addItem(label, key)

        self.preset_description = QLabel("")
        self.preset_description.setObjectName("mutedText")
        self.preset_description.setWordWrap(True)

        settings_layout.addWidget(preset_label, 1, 0)
        settings_layout.addWidget(self.preset_combo, 1, 1)
        settings_layout.addWidget(color_mode_label, 2, 0)
        settings_layout.addWidget(self.color_mapping_combo, 2, 1)
        settings_layout.addWidget(self.preset_description, 3, 0, 1, 2)

        root.addWidget(settings_card)

        mapping_card = QFrame()
        mapping_card.setObjectName("contentCard")
        mapping_layout = QVBoxLayout(mapping_card)
        mapping_layout.setContentsMargins(28, 24, 28, 28)
        mapping_layout.setSpacing(12)

        mapping_title = QLabel("Detected band mapping")
        mapping_title.setObjectName("sectionTitle")

        self.mapping_table = QTableWidget(0, 5)
        self.mapping_table.setHorizontalHeaderLabels([
            "Detected band",
            "Normalized band",
            "Color",
            "Hex",
            "Channel",
        ])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.setMinimumHeight(360)
        self.mapping_table.horizontalHeader().setStretchLastSection(True)

        mapping_layout.addWidget(mapping_title)
        mapping_layout.addWidget(self.mapping_table)

        root.addWidget(mapping_card)

        info = QFrame()
        info.setObjectName("infoCard")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(20, 14, 20, 14)

        self.info_text = QLabel(
            "Preset mappings can be changed at any time. Custom keeps its saved configuration when switching to another preset."
        )
        self.info_text.setObjectName("infoText")
        self.info_text.setWordWrap(True)

        info_layout.addWidget(self.info_text)
        root.addWidget(info)
        root.addStretch(1)

        outer.addWidget(scroll)

        self.preset_combo.currentIndexChanged.connect(self.update_preset_description)
        self.color_mapping_combo.currentIndexChanged.connect(self.on_color_mapping_mode_changed)

    def on_enter(self):
        self.wizard.footer.back_button.setEnabled(True)
        self.wizard.footer.next_button.setEnabled(True)
        self.wizard.footer.set_status("Choose object preset and color mapping.")

        self.load_from_project()
        self.rebuild_mapping_table()
        self.update_preset_description()

    def detected_bands(self) -> list[str]:
        result = getattr(self.wizard, "scan_result", None)
        if not result:
            return []

        return sorted(
            {
                item.band
                for item in result.files
                if item.kind == "object" and item.band != "-"
            }
        )

    def load_from_project(self):
        project = self.wizard.project
        if not project:
            return

        self._loading = True

        preset = getattr(project, "preset", "auto") or "auto"
        index = self.preset_combo.findData(preset)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)

        mode = project.output_options.get("color_mapping_mode", "photometric")
        mode_index = self.color_mapping_combo.findData(mode)
        if mode_index >= 0:
            self.color_mapping_combo.setCurrentIndex(mode_index)

        self._loading = False

    def update_preset_description(self):
        key = self.preset_combo.currentData()

        descriptions = {
            "auto": "The application will suggest a strategy based on detected bands and object structure.",
            "compact_galaxy": "Best for compact targets with strong central structure and surrounding background.",
            "extended_galaxy": "Best for large diffuse galaxies where object protection is important.",
            "nebula": "Conservative background correction to preserve diffuse emission.",
            "star_field": "For clusters and star fields where background can be modeled more aggressively.",
            "manual_advanced": "Expose advanced parameters in later steps.",
        }

        self.preset_description.setText(descriptions.get(key, ""))

    def on_color_mapping_mode_changed(self):
        if self._loading:
            return

        self.save_custom_mapping_from_table()
        self.rebuild_mapping_table()

    def saved_custom_mapping(self) -> dict[str, dict[str, str]]:
        project = self.wizard.project
        if not project:
            return {}

        return project.output_options.get("custom_color_mapping", {}) or {}

    def rebuild_mapping_table(self):
        bands = self.detected_bands()
        mode = self.color_mapping_combo.currentData() or "photometric"

        self.current_mapping = build_color_mapping(
            bands=bands,
            mode=mode,
            saved_custom=self.saved_custom_mapping(),
        )

        self.populate_mapping_table()

    def populate_mapping_table(self):
        mode = self.color_mapping_combo.currentData() or "photometric"
        custom = mode == "custom"

        self.mapping_table.blockSignals(True)
        self.mapping_table.setRowCount(len(self.current_mapping))

        for row, item in enumerate(self.current_mapping):
            band_item = QTableWidgetItem(item.band)
            band_item.setTextAlignment(Qt.AlignCenter)
            band_item.setFlags(band_item.flags() & ~Qt.ItemIsEditable)

            normalized_item = QTableWidgetItem(item.normalized_band)
            normalized_item.setTextAlignment(Qt.AlignCenter)
            normalized_item.setFlags(normalized_item.flags() & ~Qt.ItemIsEditable)

            self.mapping_table.setItem(row, 0, band_item)
            self.mapping_table.setItem(row, 1, normalized_item)

            color_button = QPushButton(item.color_name)
            color_button.setStyleSheet(
                f"background-color: {item.hex_color}; color: {self.text_color_for_background(item.hex_color)};"
            )
            color_button.setEnabled(custom)
            color_button.clicked.connect(lambda checked=False, r=row: self.choose_color(r))
            self.mapping_table.setCellWidget(row, 2, color_button)

            hex_edit = QLineEdit(item.hex_color)
            hex_edit.setEnabled(custom)
            hex_edit.editingFinished.connect(lambda r=row: self.on_hex_changed(r))
            self.mapping_table.setCellWidget(row, 3, hex_edit)

            channel_combo = QComboBox()
            for channel in CHANNELS:
                channel_combo.addItem(channel, channel)

            index = channel_combo.findData(item.channel)
            if index >= 0:
                channel_combo.setCurrentIndex(index)

            channel_combo.setEnabled(custom)
            channel_combo.currentIndexChanged.connect(lambda ignored=0, r=row: self.on_channel_changed(r))
            self.mapping_table.setCellWidget(row, 4, channel_combo)

            self.mapping_table.setRowHeight(row, 42)

        self.mapping_table.blockSignals(False)
        self.mapping_table.resizeColumnsToContents()

        if not self.current_mapping:
            self.info_text.setText("No object bands were detected. Go back to Files and verify the scan result.")
        elif custom:
            self.info_text.setText("Custom mode uses a Smart Default as a starting point. You can edit each color and channel.")
        else:
            self.info_text.setText("Preset mode is read-only. Switch to Custom to manually edit colors and channels.")

    def text_color_for_background(self, hex_color: str) -> str:
        value = hex_color.strip().lstrip("#")

        try:
            r = int(value[0:2], 16)
            g = int(value[2:4], 16)
            b = int(value[4:6], 16)
        except Exception:
            return "#FFFFFF"

        luminance = (0.299 * r + 0.587 * g + 0.114 * b)
        return "#000000" if luminance > 150 else "#FFFFFF"

    def choose_color(self, row: int):
        if row < 0 or row >= len(self.current_mapping):
            return

        current = QColor(self.current_mapping[row].hex_color)
        selected = QColorDialog.getColor(current, self, "Choose band color")

        if not selected.isValid():
            return

        hex_color = selected.name().upper()

        item = self.current_mapping[row]
        self.current_mapping[row] = BandColorMapping(
            band=item.band,
            normalized_band=item.normalized_band,
            color_name="Custom",
            hex_color=hex_color,
            channel=item.channel,
        )

        self.populate_mapping_table()
        self.save_custom_mapping_to_project()

    def on_hex_changed(self, row: int):
        if row < 0 or row >= len(self.current_mapping):
            return

        widget = self.mapping_table.cellWidget(row, 3)
        if not isinstance(widget, QLineEdit):
            return

        value = widget.text().strip().upper()

        if not is_valid_hex_color(value):
            widget.setText(self.current_mapping[row].hex_color)
            return

        item = self.current_mapping[row]
        self.current_mapping[row] = BandColorMapping(
            band=item.band,
            normalized_band=item.normalized_band,
            color_name="Custom",
            hex_color=value,
            channel=item.channel,
        )

        self.populate_mapping_table()
        self.save_custom_mapping_to_project()

    def on_channel_changed(self, row: int):
        if row < 0 or row >= len(self.current_mapping):
            return

        widget = self.mapping_table.cellWidget(row, 4)
        if not isinstance(widget, QComboBox):
            return

        item = self.current_mapping[row]
        self.current_mapping[row] = BandColorMapping(
            band=item.band,
            normalized_band=item.normalized_band,
            color_name=item.color_name,
            hex_color=item.hex_color,
            channel=widget.currentData() or "-",
        )

        self.save_custom_mapping_to_project()

    def save_custom_mapping_from_table(self):
        if self.color_mapping_combo.currentData() != "custom":
            return

        self.save_custom_mapping_to_project()

    def save_custom_mapping_to_project(self):
        project = self.wizard.ensure_project()
        project.output_options["custom_color_mapping"] = mapping_to_project_dict(self.current_mapping)
        project.update_timestamp()

    def save_to_project(self):
        project = self.wizard.ensure_project()

        self.save_custom_mapping_from_table()

        mode = self.color_mapping_combo.currentData() or "photometric"

        project.preset = self.preset_combo.currentData() or "auto"
        project.output_options["color_mapping_mode"] = mode
        project.output_options["color_mapping"] = mapping_to_project_dict(self.current_mapping)

        # Backward-compatible simple RGB/L mapping used by future pipeline steps.
        rgb_mapping = {
            "red": "",
            "green": "",
            "blue": "",
            "luminance": "",
        }

        for item in self.current_mapping:
            if item.channel == "R" and not rgb_mapping["red"]:
                rgb_mapping["red"] = item.band
            elif item.channel == "G" and not rgb_mapping["green"]:
                rgb_mapping["green"] = item.band
            elif item.channel == "B" and not rgb_mapping["blue"]:
                rgb_mapping["blue"] = item.band
            elif item.channel == "L" and not rgb_mapping["luminance"]:
                rgb_mapping["luminance"] = item.band
            elif item.channel == "G+B":
                if not rgb_mapping["green"]:
                    rgb_mapping["green"] = item.band
                if not rgb_mapping["blue"]:
                    rgb_mapping["blue"] = item.band
            elif item.channel == "R+G+B":
                if not rgb_mapping["red"]:
                    rgb_mapping["red"] = item.band
                if not rgb_mapping["green"]:
                    rgb_mapping["green"] = item.band
                if not rgb_mapping["blue"]:
                    rgb_mapping["blue"] = item.band

        project.output_options["band_mapping"] = rgb_mapping
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
            self.wizard.footer.set_status("Object preset and color mapping saved.")
        except Exception as exc:
            self.wizard.footer.set_status(f"Could not autosave color mapping: {exc}")

    def on_leave(self, target_index: int):
        self.persist_settings()

    def on_next(self) -> bool:
        self.persist_settings()
        self.wizard.go_to_step(5)
        return False

