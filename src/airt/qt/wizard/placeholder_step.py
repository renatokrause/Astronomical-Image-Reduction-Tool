from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderStep(QWidget):
    def __init__(self, wizard, title: str, description: str):
        super().__init__()
        self.wizard = wizard

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")

        desc_label = QLabel(description)
        desc_label.setObjectName("pageSubtitle")
        desc_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(desc_label)
        layout.addStretch(1)

    def on_enter(self):
        self.wizard.footer.back_button.setEnabled(True)
        self.wizard.footer.next_button.setEnabled(True)
        self.wizard.footer.set_status("This step will be implemented next.")
