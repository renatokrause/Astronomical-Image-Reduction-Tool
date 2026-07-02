from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QSizePolicy,
    QScrollArea,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
)

from airt.project.recent import load_recent_projects
from airt.qt.widgets.action_card import ActionCard


def resource_root() -> Path:
    return Path(__file__).resolve().parents[2] / "resources"


class HeroBanner(QFrame):
    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)

        self.setObjectName("heroBanner")
        self.setMinimumHeight(250)
        self.setMaximumHeight(280)
        self._pixmap = QPixmap(str(image_path)) if image_path.exists() else QPixmap()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(42, 34, 42, 34)
        layout.setSpacing(8)

        title = QLabel("Welcome to AIRT")
        title.setObjectName("heroBannerTitle")
        title.setTextFormat(Qt.RichText)

        subtitle = QLabel("Astronomical Image Reduction Tool")
        subtitle.setObjectName("heroBannerSubtitle")

        description = QLabel("Calibrate · Align · Stack · Color · Export")
        description.setObjectName("heroBannerDescription")

        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(description)
        layout.addStretch(1)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = 18

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter.save()
        painter.setClipPath(path)

        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.rect().size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            x = max(0, (scaled.width() - self.width()) // 2)
            y = max(0, (scaled.height() - self.height()) // 2)
            cropped = scaled.copy(x, y, self.width(), self.height())
            painter.drawPixmap(self.rect(), cropped)
        else:
            painter.fillRect(self.rect(), QColor("#101a2d"))

        painter.fillRect(self.rect(), QColor(0, 0, 0, 55))
        painter.restore()

        painter.setPen(QPen(QColor("#263956"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        super().paintEvent(event)


class WelcomeStep(QWidget):
    def __init__(self, wizard):
        super().__init__()

        self.wizard = wizard

        resources = resource_root()
        icons = resources / "icons"
        images = resources / "images"

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
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(22)

        hero = HeroBanner(images / "hero_astro.jpg")
        root.addWidget(hero)

        cards = QHBoxLayout()
        cards.setSpacing(20)

        self.new_card = ActionCard(
            title="New reduction project",
            description="Create a new project and start a new reduction workflow.",
            icon_path=icons / "new_project.png",
            primary=True,
        )

        self.open_card = ActionCard(
            title="Open previous project",
            description="Open an existing .airt.json project file and continue your work.",
            icon_path=icons / "open_project.png",
            primary=False,
        )

        self.new_card.setMinimumHeight(138)
        self.open_card.setMinimumHeight(138)

        cards.addWidget(self.new_card, 1)
        cards.addWidget(self.open_card, 1)

        root.addLayout(cards)

        recent_title = QLabel("Recent projects")
        recent_title.setObjectName("sectionTitle")
        recent_title.setMinimumHeight(34)

        root.addWidget(recent_title)

        self.recent_card = QFrame()
        self.recent_card.setObjectName("emptyCard")
        self.recent_card.setFixedHeight(360)

        recent_layout = QVBoxLayout(self.recent_card)
        recent_layout.setContentsMargins(18, 14, 18, 14)
        recent_layout.setSpacing(8)

        self.no_recent_label = QLabel("No recent projects\nYour recently opened projects will appear here.")
        self.no_recent_label.setObjectName("mutedText")
        self.no_recent_label.setAlignment(Qt.AlignCenter)
        self.no_recent_label.setWordWrap(True)

        self.recent_list = QListWidget()
        self.recent_list.setFixedHeight(315)
        self.recent_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.recent_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_list.setVisible(False)
        self.recent_list.itemDoubleClicked.connect(self.open_recent_project)

        recent_layout.addWidget(self.no_recent_label, 1)
        recent_layout.addWidget(self.recent_list, 0)

        root.addWidget(self.recent_card)

        info = QFrame()
        info.setObjectName("infoCard")
        info.setMinimumHeight(86)
        info.setMaximumHeight(110)

        info_layout = QHBoxLayout(info)
        info_layout.setContentsMargins(20, 14, 20, 14)
        info_layout.setSpacing(16)

        info_icon = QLabel()
        info_icon.setObjectName("infoIcon")
        info_icon.setFixedSize(36, 36)
        info_icon.setAlignment(Qt.AlignCenter)

        info_pixmap = QPixmap(str(icons / "info.png"))
        if not info_pixmap.isNull():
            info_icon.setPixmap(
                info_pixmap.scaled(
                    30,
                    30,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )

        info_text = QLabel(
            "Projects are saved as .airt.json files and include all settings, selections and "
            "processing parameters.\nYour image files remain in their original locations."
        )
        info_text.setWordWrap(True)
        info_text.setObjectName("infoText")

        info_layout.addWidget(info_icon)
        info_layout.addWidget(info_text, 1)

        root.addWidget(info)
        root.addStretch(1)

        outer.addWidget(scroll)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def refresh_recent_projects(self):
        projects = load_recent_projects()
        self.recent_list.clear()

        if not projects:
            self.recent_list.setVisible(False)
            self.no_recent_label.setVisible(True)
            return

        self.no_recent_label.setVisible(False)
        self.recent_list.setVisible(True)

        for project in projects[:5]:
            item = QListWidgetItem(f"{project['name']}\n{project['path']}")
            item.setData(Qt.UserRole, project["path"])
            item.setSizeHint(QSize(0, 58))
            self.recent_list.addItem(item)

    def open_recent_project(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole)

        if path:
            self.wizard.open_project_path(path)

    def on_enter(self):
        self.refresh_recent_projects()
        self.wizard.footer.back_button.setEnabled(False)
        self.wizard.footer.next_button.setEnabled(True)
        self.wizard.footer.set_status("Ready · No project loaded")

    def on_next(self) -> bool:
        self.wizard.go_to_step(1)
        return False
