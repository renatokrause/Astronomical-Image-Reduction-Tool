from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QProgressBar,
    QListWidget,
    QListWidgetItem,
)

from airt.core.final_render import (
    build_final_image,
    save_final_outputs,
    output_folder_for_project,
    object_name_for_project,
)


class ProcessingStep(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self.generated_files: list[Path] = []

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
            "Generate the final image files using the selected frames and saved project settings."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        root.addWidget(title)
        root.addWidget(subtitle)

        summary_card = QFrame()
        summary_card.setObjectName("contentCard")
        summary_layout = QGridLayout(summary_card)
        summary_layout.setContentsMargins(24, 20, 24, 24)
        summary_layout.setHorizontalSpacing(14)
        summary_layout.setVerticalSpacing(12)
        summary_layout.setColumnMinimumWidth(0, 160)
        summary_layout.setColumnStretch(1, 1)

        summary_title = QLabel("Summary")
        summary_title.setObjectName("sectionTitle")

        self.object_label = QLabel("")
        self.output_label = QLabel("")
        self.formats_label = QLabel("")
        self.frames_label = QLabel("")
        self.bands_label = QLabel("")

        for label in [
            self.object_label,
            self.output_label,
            self.formats_label,
            self.frames_label,
            self.bands_label,
        ]:
            label.setObjectName("mutedText")
            label.setWordWrap(True)

        summary_layout.addWidget(summary_title, 0, 0, 1, 2)
        summary_layout.addWidget(QLabel("Object"), 1, 0)
        summary_layout.addWidget(self.object_label, 1, 1)
        summary_layout.addWidget(QLabel("Output folder"), 2, 0)
        summary_layout.addWidget(self.output_label, 2, 1)
        summary_layout.addWidget(QLabel("Formats"), 3, 0)
        summary_layout.addWidget(self.formats_label, 3, 1)
        summary_layout.addWidget(QLabel("Selected frames"), 4, 0)
        summary_layout.addWidget(self.frames_label, 4, 1)
        summary_layout.addWidget(QLabel("Bands"), 5, 0)
        summary_layout.addWidget(self.bands_label, 5, 1)

        root.addWidget(summary_card)

        progress_card = QFrame()
        progress_card.setObjectName("contentCard")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(24, 20, 24, 24)
        progress_layout.setSpacing(12)

        progress_title = QLabel("Processing")
        progress_title.setObjectName("sectionTitle")

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("mutedText")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.generated_list = QListWidget()
        self.generated_list.setMinimumHeight(180)

        progress_layout.addWidget(progress_title)
        progress_layout.addWidget(self.status_label)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.generated_list)

        root.addWidget(progress_card)

        actions_card = QFrame()
        actions_card.setObjectName("contentCard")
        actions_layout = QHBoxLayout(actions_card)
        actions_layout.setContentsMargins(18, 14, 18, 14)
        actions_layout.setSpacing(10)

        actions_title = QLabel("Actions")
        actions_title.setObjectName("sectionTitle")

        self.start_button = QPushButton("Start processing")
        self.start_button.clicked.connect(self.start_processing)

        self.open_folder_button = QPushButton("Open output folder")
        self.open_folder_button.clicked.connect(self.open_output_folder)
        self.open_folder_button.setEnabled(False)

        actions_layout.addWidget(actions_title)
        actions_layout.addStretch(1)
        actions_layout.addWidget(self.start_button)
        actions_layout.addWidget(self.open_folder_button)

        root.addWidget(actions_card)
        root.addStretch(1)

        outer.addWidget(scroll)

    def on_enter(self):
        self.wizard.footer.back_button.setEnabled(True)
        self.wizard.footer.next_button.setEnabled(False)
        self.wizard.footer.set_status("Ready to process final outputs.")
        self.refresh_summary()

    def refresh_summary(self):
        project = self.wizard.project

        if not project:
            return

        selected = getattr(project, "selected_object_files", {}) or {}
        bands = [band for band, paths in selected.items() if paths]
        frame_count = sum(len(paths) for paths in selected.values())

        export = project.output_options.get("final_export", {}) or {}
        formats = export.get("formats", {}) or {}

        enabled_formats = [
            name.upper()
            for name, enabled in formats.items()
            if enabled
        ]

        self.object_label.setText(object_name_for_project(project))
        self.output_label.setText(str(output_folder_for_project(project)))
        self.formats_label.setText(", ".join(enabled_formats) if enabled_formats else "None")
        self.frames_label.setText(str(frame_count))
        self.bands_label.setText(", ".join(bands) if bands else "None")

    def start_processing(self):
        project = self.wizard.project

        if not project:
            return

        export = project.output_options.get("final_export", {}) or {}
        formats = export.get("formats", {}) or {}

        if not any(formats.values()):
            self.status_label.setText("No output format selected.")
            return

        self.generated_list.clear()
        self.generated_files = []
        self.start_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)

        try:
            self.progress_bar.setValue(10)
            self.status_label.setText("Rendering final image...")

            result = build_final_image(project)

            self.progress_bar.setValue(65)
            self.status_label.setText("Saving output files...")

            self.generated_files = save_final_outputs(project, result, export)

            self.progress_bar.setValue(100)
            self.status_label.setText("Done.")

            for path in self.generated_files:
                self.generated_list.addItem(QListWidgetItem(str(path)))

            self.open_folder_button.setEnabled(True)
            self.wizard.footer.set_status("Final files generated.")

            if export.get("open_output_folder", False):
                self.open_output_folder()

        except Exception as exc:
            self.status_label.setText(f"Processing failed: {exc}")
            self.progress_bar.setValue(0)
            self.wizard.footer.set_status(f"Processing failed: {exc}")
        finally:
            self.start_button.setEnabled(True)

    def open_output_folder(self):
        project = self.wizard.project

        if not project:
            return

        folder = output_folder_for_project(project)
        folder.mkdir(parents=True, exist_ok=True)

        if sys.platform.startswith("win"):
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
