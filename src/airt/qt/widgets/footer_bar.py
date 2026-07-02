from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class FooterBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("footerBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 14, 22, 14)
        layout.setSpacing(10)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusText")
        self.status_label.setAlignment(Qt.AlignVCenter)

        layout.addWidget(self.status_label, 1)

        self.save_button = QPushButton("Save project")
        self.cancel_button = QPushButton("Cancel")
        self.back_button = QPushButton("Back")
        self.next_button = QPushButton("Next")

        self.next_button.setObjectName("primaryButton")

        self.save_button.setMinimumWidth(135)
        self.cancel_button.setMinimumWidth(105)
        self.back_button.setMinimumWidth(105)
        self.next_button.setMinimumWidth(135)

        self.save_button.setMinimumHeight(46)
        self.cancel_button.setMinimumHeight(46)
        self.back_button.setMinimumHeight(46)
        self.next_button.setMinimumHeight(46)

        layout.addWidget(self.save_button)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.back_button)
        layout.addWidget(self.next_button)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)
