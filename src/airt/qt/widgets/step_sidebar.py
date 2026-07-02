from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class StepSidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("stepSidebar")
        self.setFixedWidth(410)

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

        self.items: list[QFrame] = []
        self.number_labels: list[QLabel] = []
        self.title_labels: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 22, 20, 22)
        layout.setSpacing(8)

        for index, name in enumerate(self.steps, start=1):
            item = QFrame()
            item.setObjectName("sidebarStepItem")
            item.setMinimumHeight(46)

            row = QHBoxLayout(item)
            row.setContentsMargins(12, 8, 12, 8)
            row.setSpacing(12)

            number = QLabel(str(index))
            number.setObjectName("sidebarStepNumber")
            number.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            number.setFixedWidth(26)

            title = QLabel(name)
            title.setObjectName("sidebarStepTitle")
            title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            title.setWordWrap(True)
            title.setMinimumWidth(0)

            row.addWidget(number)
            row.addWidget(title, 1)

            self.items.append(item)
            self.number_labels.append(number)
            self.title_labels.append(title)

            layout.addWidget(item)

        layout.addStretch(1)
        self.set_current_step(0)

    def set_current_step(self, current_index: int) -> None:
        for index, item in enumerate(self.items):
            active = index == current_index

            item.setProperty("active", active)
            self.number_labels[index].setProperty("active", active)
            self.title_labels[index].setProperty("active", active)

            for widget in [item, self.number_labels[index], self.title_labels[index]]:
                widget.style().unpolish(widget)
                widget.style().polish(widget)
