from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QMessageBox,
)

from airt.qt.widgets.fits_preview_dialog import FitsPreviewDialog
from airt.project import autosave_project


class FrameReviewStep(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self.all_files = []
        self.displayed_files = []
        self.selection_state: dict[str, bool] = {}
        self._loading_table = False

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
        root.setSpacing(20)

        title = QLabel("Review frames")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Choose which object and calibration frames will be used. "
            "Unchecked files will be ignored in later processing steps."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        root.addWidget(title)
        root.addWidget(subtitle)

        controls = QHBoxLayout()

        self.kind_filter = QComboBox()
        self.kind_filter.currentIndexChanged.connect(self.on_filter_changed)

        self.band_filter = QComboBox()
        self.band_filter.currentIndexChanged.connect(self.on_filter_changed)

        self.select_visible_button = QPushButton("Select all")
        self.select_visible_button.clicked.connect(lambda: self.set_visible_checked(True))

        self.clear_visible_button = QPushButton("Clear")
        self.clear_visible_button.clicked.connect(lambda: self.set_visible_checked(False))

        self.preview_button = QPushButton("Preview")
        self.preview_button.clicked.connect(self.preview_selected_visible)

        controls.addWidget(QLabel("Type:"))
        controls.addWidget(self.kind_filter)

        controls.addWidget(QLabel("Band:"))
        controls.addWidget(self.band_filter)

        controls.addStretch(1)
        controls.addWidget(self.select_visible_button)
        controls.addWidget(self.clear_visible_button)
        controls.addWidget(self.preview_button)

        root.addLayout(controls)

        table_card = QFrame()
        table_card.setObjectName("contentCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(22, 18, 22, 22)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Use",
            "Type",
            "Band",
            "File",
            "Exposure",
            "Size",
            "Binning",
            "Status",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(460)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self.on_table_item_changed)

        table_layout.addWidget(self.table)
        root.addWidget(table_card)

        info = QFrame()
        info.setObjectName("infoCard")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(20, 14, 20, 14)

        self.summary_label = QLabel("No frames loaded.")
        self.summary_label.setObjectName("infoText")
        self.summary_label.setWordWrap(True)

        info_layout.addWidget(self.summary_label)
        root.addWidget(info)
        root.addStretch(1)

        outer.addWidget(scroll)

    def on_enter(self):
        self.wizard.footer.back_button.setEnabled(True)
        self.wizard.footer.next_button.setEnabled(True)
        self.wizard.footer.set_status("Review object and calibration frames.")
        self.load_from_scan_result()

    def display_kind(self, kind: str) -> str:
        if kind == "object":
            return "OBJECT"
        return kind.upper()

    def display_band(self, band: str) -> str:
        return "None" if band == "-" else band

    def load_from_scan_result(self):
        result = getattr(self.wizard, "scan_result", None)

        if not result:
            QMessageBox.information(
                self,
                "No scan result",
                "No scan result is available. Go back to Files and scan the project first.",
            )
            self.all_files = []
            self.displayed_files = []
            self.selection_state = {}
            self.populate_filters()
            self.populate_table()
            return

        self.all_files = list(result.files)
        self.initialize_selection_state()
        self.populate_filters()
        self.populate_table()

    def initialize_selection_state(self):
        project = self.wizard.project
        previous_state = dict(self.selection_state)
        self.selection_state = {}

        selected_paths = set()
        rejected_paths = set()

        if project:
            for values in getattr(project, "selected_object_files", {}).values():
                selected_paths.update(values)

            for values in getattr(project, "rejected_object_files", {}).values():
                rejected_paths.update(values)

            for values in getattr(project, "selected_calibration_files", {}).values():
                selected_paths.update(values)

            for values in getattr(project, "rejected_calibration_files", {}).values():
                rejected_paths.update(values)

        for item in self.all_files:
            if item.path in previous_state:
                self.selection_state[item.path] = previous_state[item.path]
            elif item.path in rejected_paths:
                self.selection_state[item.path] = False
            elif item.path in selected_paths:
                self.selection_state[item.path] = True
            else:
                self.selection_state[item.path] = item.status != "Error"

    def on_filter_changed(self):
        self.sync_displayed_selection()
        self.populate_table()

    def populate_filters(self):
        current_kind_data = self.kind_filter.currentData()
        current_band_data = self.band_filter.currentData()

        self.kind_filter.blockSignals(True)
        self.band_filter.blockSignals(True)

        self.kind_filter.clear()
        self.kind_filter.addItem("All", "")

        for kind in ["object", "bias", "dark", "flat", "focus"]:
            if any(item.kind == kind for item in self.all_files):
                self.kind_filter.addItem(self.display_kind(kind), kind)

        self.band_filter.clear()
        self.band_filter.addItem("All", "")

        bands = sorted({item.band for item in self.all_files})
        for band in bands:
            self.band_filter.addItem(self.display_band(band), band)

        kind_index = self.kind_filter.findData(current_kind_data)
        if kind_index >= 0:
            self.kind_filter.setCurrentIndex(kind_index)

        band_index = self.band_filter.findData(current_band_data)
        if band_index >= 0:
            self.band_filter.setCurrentIndex(band_index)

        self.kind_filter.blockSignals(False)
        self.band_filter.blockSignals(False)

    def filtered_files(self):
        kind_data = self.kind_filter.currentData()
        band_data = self.band_filter.currentData()

        files = self.all_files

        if kind_data:
            files = [item for item in files if item.kind == kind_data]

        if band_data:
            files = [item for item in files if item.band == band_data]

        return files

    def populate_table(self):
        self.displayed_files = self.filtered_files()

        self.table.blockSignals(True)
        self.table.setRowCount(len(self.displayed_files))

        for row, item in enumerate(self.displayed_files):
            use_item = QTableWidgetItem()
            use_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            use_item.setCheckState(Qt.Checked if self.selection_state.get(item.path, False) else Qt.Unchecked)

            size = "-"
            if item.naxis1 and item.naxis2:
                size = f"{item.naxis1} × {item.naxis2}"

            exposure = "-" if item.exptime is None else f"{item.exptime:g}s"
            status = item.status if not item.problem else f"{item.status}: {item.problem}"

            values = [
                use_item,
                self.display_kind(item.kind),
                self.display_band(item.band),
                Path(item.path).name,
                exposure,
                size,
                item.binning,
                status,
            ]

            self.table.setItem(row, 0, use_item)

            for col, value in enumerate(values[1:], start=1):
                table_item = QTableWidgetItem(str(value))

                if col in {1, 2, 4, 5, 6}:
                    table_item.setTextAlignment(Qt.AlignCenter)

                self.table.setItem(row, col, table_item)

            self.table.setRowHeight(row, 34)

        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.update_summary()

    def sync_displayed_selection(self):
        for row, item in enumerate(self.displayed_files):
            checkbox = self.table.item(row, 0)
            if checkbox:
                self.selection_state[item.path] = checkbox.checkState() == Qt.Checked

    def set_visible_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked

        self._loading_table = True
        self.table.blockSignals(True)

        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(state)

        self.table.blockSignals(False)
        self._loading_table = False

        self.sync_displayed_selection()
        self.update_summary()
        self.persist_selection()

    def on_table_item_changed(self, item):
        if self._loading_table:
            return

        if item.column() != 0:
            return

        self.sync_displayed_selection()
        self.update_summary()
        self.persist_selection()

    def persist_selection(self):
        if not self.wizard.project:
            return

        self.save_to_project()

        try:
            if self.wizard.project.project_file:
                autosave_project(self.wizard.project)
                if hasattr(self.wizard, "mark_project_recent"):
                    self.wizard.mark_project_recent()
                self.wizard.footer.set_status("Frame selection saved.")
        except Exception as exc:
            self.wizard.footer.set_status(f"Could not autosave frame selection: {exc}")

    def preview_selected_visible(self):
        self.sync_displayed_selection()

        selected_visible = [
            item
            for item in self.displayed_files
            if self.selection_state.get(item.path, False)
        ]

        if not selected_visible:
            QMessageBox.information(
                self,
                "No selected files",
                "There are no selected files in the current filter.",
            )
            return

        dialog = FitsPreviewDialog(selected_visible, self)
        dialog.exec()

    def save_to_project(self):
        self.sync_displayed_selection()

        project = self.wizard.ensure_project()

        project.selected_object_files = {}
        project.rejected_object_files = {}

        if not hasattr(project, "selected_calibration_files"):
            project.selected_calibration_files = {}

        if not hasattr(project, "rejected_calibration_files"):
            project.rejected_calibration_files = {}

        project.selected_calibration_files = {}
        project.rejected_calibration_files = {}

        for item in self.all_files:
            selected = self.selection_state.get(item.path, False)

            if item.kind == "object":
                if selected:
                    project.selected_object_files.setdefault(item.band, []).append(item.path)
                else:
                    project.rejected_object_files.setdefault(item.band, []).append(item.path)
            else:
                key = f"{item.kind}:{item.band}"
                if selected:
                    project.selected_calibration_files.setdefault(key, []).append(item.path)
                else:
                    project.rejected_calibration_files.setdefault(key, []).append(item.path)

        project.update_timestamp()

    def update_summary(self):
        total = len(self.all_files)
        selected = sum(1 for item in self.all_files if self.selection_state.get(item.path, False))
        rejected = total - selected

        by_kind = {}
        for item in self.all_files:
            by_kind.setdefault(item.kind, {"total": 0, "selected": 0})
            by_kind[item.kind]["total"] += 1
            if self.selection_state.get(item.path, False):
                by_kind[item.kind]["selected"] += 1

        parts = []
        for kind in ["object", "bias", "dark", "flat", "focus"]:
            if kind in by_kind:
                parts.append(
                    f"{self.display_kind(kind)}: {by_kind[kind]['selected']}/{by_kind[kind]['total']} selected"
                )

        self.summary_label.setText(
            f"Total files: {total}. Selected: {selected}. Rejected: {rejected}. "
            + " | ".join(parts)
        )

    def on_next(self) -> bool:
        self.save_to_project()
        self.wizard.footer.set_status("Frame selection saved.")
        self.wizard.go_to_step(4)
        return False

