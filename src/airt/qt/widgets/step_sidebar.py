from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class StepSidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stepSidebar")

        self.steps = [
            "Welcome",
            "Project Folders",
            "File Scan",
            "Frame Selection",
            "Preset & Color Mapping",
            "Alignment",
            "Background Correction",
            "Final Composition & Export",
            "Process & Save",
        ]
        self.labels: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 16, 22)
        layout.setSpacing(8)

        for index, name in enumerate(self.steps, start=1):
            label = QLabel(f"{index}   {name}")
            label.setObjectName("sidebarStep")
            label.setAlignment(Qt.AlignVCenter)
            label.setMinimumHeight(42)
            self.labels.append(label)
            layout.addWidget(label)

        layout.addStretch(1)

        self.set_current_step(0)

    def set_current_step(self, current_index: int) -> None:
        for index, label in enumerate(self.labels):
            label.setProperty("active", index == current_index)
            label.style().unpolish(label)
            label.style().polish(label)
