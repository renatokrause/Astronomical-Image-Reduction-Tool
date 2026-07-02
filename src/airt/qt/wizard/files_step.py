from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from airt.core.file_scan import scan_project_files


class FilesStep(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self.scan_result = None
        self._has_scanned = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("pageScroll")

        content = QWidget()
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(48, 42, 48, 42)
        root.setSpacing(20)

        header = QHBoxLayout()

        title_box = QVBoxLayout()
        title_box.setSpacing(8)

        title = QLabel("Scan and validate files")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Scan FITS files, detect all available bands, and check whether the project has the data needed for reduction."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self.scan_button = QPushButton("Scan files")
        self.scan_button.setMinimumHeight(44)
        self.scan_button.clicked.connect(self.run_scan)

        header.addLayout(title_box, 1)
        header.addWidget(self.scan_button, 0, Qt.AlignBottom)

        root.addLayout(header)

        progress_card = QFrame()
        progress_card.setObjectName("contentCard")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(22, 18, 22, 18)
        progress_layout.setSpacing(10)

        self.progress_label = QLabel("Ready to scan.")
        self.progress_label.setObjectName("mutedText")

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar)

        root.addWidget(progress_card)

        summary_card = QFrame()
        summary_card.setObjectName("contentCard")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(22, 18, 22, 22)
        summary_layout.setSpacing(12)

        summary_title = QLabel("Detected files by type and band")
        summary_title.setObjectName("sectionTitle")

        self.summary_table = QTableWidget(0, 5)
        self.summary_table.setHorizontalHeaderLabels(["Type", "Band", "Count", "Status", "Problems"])
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setAlternatingRowColors(False)
        self.summary_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.setMinimumHeight(240)

        self.summary_table.horizontalHeader().setStretchLastSection(True)

        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(self.summary_table)

        root.addWidget(summary_card)

        bands_card = QFrame()
        bands_card.setObjectName("infoCard")
        bands_layout = QVBoxLayout(bands_card)
        bands_layout.setContentsMargins(20, 14, 20, 14)

        self.bands_label = QLabel(
            "Detected bands will appear here. Band-to-color mapping will be configured in a later step."
        )
        self.bands_label.setObjectName("infoText")
        self.bands_label.setWordWrap(True)

        bands_layout.addWidget(self.bands_label)
        root.addWidget(bands_card)

        problems_card = QFrame()
        problems_card.setObjectName("contentCard")
        problems_layout = QVBoxLayout(problems_card)
        problems_layout.setContentsMargins(22, 18, 22, 22)
        problems_layout.setSpacing(12)

        problems_title = QLabel("Validation messages")
        problems_title.setObjectName("sectionTitle")

        self.problems_text = QTextEdit()
        self.problems_text.setReadOnly(True)
        self.problems_text.setMinimumHeight(150)
        self.problems_text.setPlaceholderText("No scan performed yet.")

        problems_layout.addWidget(problems_title)
        problems_layout.addWidget(self.problems_text)

        root.addWidget(problems_card)
        root.addStretch(1)

        outer.addWidget(scroll)

    def on_enter(self):
        self.wizard.footer.back_button.setEnabled(True)
        self.wizard.footer.next_button.setEnabled(True)
        self.wizard.footer.set_status("Scan FITS files and validate detected bands.")

        if self.wizard.project:
            if hasattr(self.wizard, "hide_wait_overlay"):
                self.wizard.hide_wait_overlay()

            self.run_scan()

    def _progress(self, value: int, total: int, message: str) -> None:
        total = max(total, 1)
        percent = int((value / total) * 100)

        self.progress_bar.setValue(percent)
        self.progress_label.setText(message)
        self.wizard.footer.set_status(message)

        QApplication.processEvents()

    def run_scan(self) -> None:
        project = self.wizard.project

        if not project:
            QMessageBox.warning(self, "No project", "Create or open a project before scanning files.")
            return

        self.scan_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Starting scan...")
        self.summary_table.setRowCount(0)
        self.problems_text.clear()
        QApplication.processEvents()

        try:
            self.scan_result = scan_project_files(project, progress_callback=self._progress)
            self._has_scanned = True
            self.wizard.scan_result = self.scan_result
        except Exception as exc:
            QMessageBox.critical(self, "Scan failed", str(exc))
            self.scan_button.setEnabled(True)
            return

        self.populate_summary()
        self.populate_problems()

        self.progress_bar.setValue(100)
        self.progress_label.setText("Scan complete.")
        self.wizard.footer.set_status("Scan complete.")
        self.scan_button.setEnabled(True)

    def display_band(self, band: str) -> str:
        return "None" if band == "-" else band

    def populate_summary(self) -> None:
        result = self.scan_result
        if not result:
            return

        self.summary_table.setRowCount(len(result.summary))

        for row_index, row in enumerate(result.summary):
            values = [
                row.kind.upper(),
                self.display_band(row.band),
                str(row.count),
                row.status,
                row.problems,
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignVCenter | (Qt.AlignCenter if column in {1, 2, 3} else Qt.AlignLeft))
                self.summary_table.setItem(row_index, column, item)

        self.summary_table.resizeColumnsToContents()

        bands = sorted(
            {item.band for item in result.files if item.kind in {"object", "flat", "focus"} and item.band != "-"}
        )

        if bands:
            self.bands_label.setText(
                "Detected bands: "
                + ", ".join(self.display_band(band) for band in bands)
                + ". Band-to-color mapping will be configured in a later step."
            )
        else:
            self.bands_label.setText(
                "No bands were detected. Check FITS headers such as FILTER, FILTER1, FILT, BAND, or file names."
            )

    def populate_problems(self) -> None:
        result = self.scan_result
        if not result:
            return

        if not result.problems:
            self.problems_text.setPlainText("No validation problems detected.")
            return

        self.problems_text.setPlainText("\n".join(f"- {problem}" for problem in result.problems))

    def on_next(self) -> bool:
        if not self.scan_result:
            self.run_scan()

        self.wizard.go_to_step(3)
        return False
