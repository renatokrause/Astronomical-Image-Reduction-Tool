from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout


class ActionCard(QFrame):
    clicked = Signal()

    def __init__(
        self, title: str, description: str, icon_path: str | Path | None = None, primary: bool = False, parent=None
    ):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)

        self.setObjectName("actionCardPrimary" if primary else "actionCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(132)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(24)

        icon_box = QLabel()
        icon_box.setObjectName("actionCardIcon")
        icon_box.setAlignment(Qt.AlignCenter)
        icon_box.setFixedSize(92, 92)

        if icon_path:
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                icon_box.setPixmap(pixmap.scaled(86, 86, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        text_layout = QVBoxLayout()
        text_layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("actionCardTitle")

        desc_label = QLabel(description)
        desc_label.setObjectName("actionCardDescription")
        desc_label.setWordWrap(True)

        text_layout.addStretch(1)
        text_layout.addWidget(title_label)
        text_layout.addWidget(desc_label)
        text_layout.addStretch(1)

        arrow = QLabel("›")
        arrow.setObjectName("actionCardArrow")
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setFixedWidth(28)

        layout.addWidget(icon_box)
        layout.addLayout(text_layout, 1)
        layout.addWidget(arrow)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
