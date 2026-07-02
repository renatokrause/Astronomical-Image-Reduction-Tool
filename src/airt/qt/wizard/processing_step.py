from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QProgressBar,
)

from airt.project import autosave_project
from airt.core.final_render import (
    build_final_image,
    save_final_outputs,
    output_folder_for_project,
)


class ProcessingStep(QWidget):
    def __init__(self, wizard):
        super().__init__()

        self.wizard = wizard
        self.generated_files: list[Path] = []
        self.processing = False
        self.finished = False

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

        title = QLabel("Process & Save")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Generate the final image files automatically using the selected frames and saved project settings."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        root.addWidget(title)
        root.addWidget(subtitle)

        progress_card = QFrame()
        progress_card.setObjectName("contentCard")

        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(24, 20, 24, 24)
        progress_layout.setSpacing(14)

        section_title = QLabel("Process & Save")
        section_title.setObjectName("sectionTitle")

        self.status_label = QLabel("Processing will start automatically.")
        self.status_label.setObjectName("mutedText")
        self.status_label.setWordWrap(True)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        progress_layout.addWidget(section_title)
        progress_layout.addWidget(self.status_label)
        progress_layout.addWidget(self.progress_bar)

        root.addWidget(progress_card)
        root.addStretch(1)

        outer.addWidget(scroll)

    def on_enter(self):
        self.finished = False
        self.generated_files = []
        self.progress_bar.setValue(0)
        self.status_label.setText("Processing will start automatically.")

        self.wizard.footer.back_button.setEnabled(False)

        if hasattr(self.wizard.footer, "cancel_button"):
            self.wizard.footer.cancel_button.setVisible(False)

        self.wizard.footer.next_button.setText("Finish")
        self.wizard.footer.next_button.setEnabled(False)
        self.wizard.footer.set_status("Processing final outputs.")

        QTimer.singleShot(250, self.start_processing)

    def on_leave(self, target_index: int):
        if hasattr(self.wizard.footer, "cancel_button"):
            self.wizard.footer.cancel_button.setVisible(True)

        self.wizard.footer.next_button.setText("Next")

    def report_progress(self, value: int, message: str):
        self.progress_bar.setValue(int(value))
        self.status_label.setText(message)
        QApplication.processEvents()

    def start_processing(self):
        if self.processing:
            return

        project = self.wizard.project

        if not project:
            self.fail_processing("No project is loaded.")
            return

        export = project.output_options.get("final_export", {}) or {}
        formats = export.get("formats", {}) or {}

        if not any(formats.values()):
            self.fail_processing("No output format selected.")
            return

        self.processing = True
        self.finished = False
        self.generated_files = []

        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            self.report_progress(5, "Starting final processing.")
            self.wizard.footer.set_status("Processing final image.")

            result = build_final_image(project, progress_callback=self.report_progress)

            self.report_progress(85, "Saving selected output formats.")
            self.generated_files = save_final_outputs(project, result, export)

            generated_text = "\\n".join(str(path) for path in self.generated_files)
            self.report_progress(100, f"Done. Final files generated:\\n{generated_text}")

            self.finished = True
            self.wizard.footer.next_button.setEnabled(True)
            self.wizard.footer.back_button.setEnabled(True)
            self.wizard.footer.set_status("Processing finished. Click Finish to close.")

            if export.get("open_output_folder", False):
                self.open_output_folder()

        except Exception as exc:
            self.fail_processing(str(exc))
        finally:
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

            self.processing = False

    def fail_processing(self, message: str):
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Processing failed: {message}")
        self.finished = False

        self.wizard.footer.back_button.setEnabled(True)
        self.wizard.footer.next_button.setEnabled(False)
        self.wizard.footer.set_status(f"Processing failed: {message}")

    def open_output_folder(self):
        project = self.wizard.project

        if not project:
            return

        folder = output_folder_for_project(project)
        folder.mkdir(parents=True, exist_ok=True)

        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception:
            pass

    def on_next(self) -> bool:
        if not self.finished:
            return False

        project = self.wizard.project

        if project and project.project_file:
            try:
                autosave_project(project)
            except Exception:
                pass

        self.wizard.close()
        return False
