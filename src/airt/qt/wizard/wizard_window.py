from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QFileDialog,
    QMessageBox,
    QApplication,
    QFrame,
)

from airt.project import ReductionProject, load_project, save_project
from airt.project.recent import add_recent_project, default_projects_dir
from airt.qt.widgets.step_sidebar import StepSidebar
from airt.qt.widgets.footer_bar import FooterBar
from airt.qt.wizard.welcome_step import WelcomeStep
from airt.qt.wizard.folders_step import FolderSelectionStep
from airt.qt.wizard.placeholder_step import PlaceholderStep
from airt.qt.wizard.files_step import FilesStep
from airt.qt.wizard.frame_review_step import FrameReviewStep
from airt.qt.wizard.preset_step import PresetStep
from airt.qt.wizard.alignment_step import AlignmentStep
from airt.qt.wizard.background_step import BackgroundStep
from airt.qt.theme import apply_dark_theme


def icons_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "resources" / "icons"


class WizardWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.project: ReductionProject | None = None
        self.scan_result = None

        self.setWindowTitle("Astronomical Image Reduction Tool")
        self.resize(1500, 960)
        self.setMinimumSize(1200, 800)

        root = QWidget()
        self.root = root
        self.setCentralWidget(root)

        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.header = self._build_header()
        main_layout.addWidget(self.header)

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(14, 0, 14, 0)
        content_layout.setSpacing(12)

        self.sidebar = StepSidebar()
        self.sidebar.setFixedWidth(260)

        self.stack = QStackedWidget()

        content_layout.addWidget(self.sidebar)
        content_layout.addWidget(self.stack, 1)

        main_layout.addWidget(content, 1)

        self.footer = FooterBar()
        main_layout.addWidget(self.footer)

        self.wait_overlay = self._build_wait_overlay()

        self.steps = [
            WelcomeStep(self),
            FolderSelectionStep(self),
            FilesStep(self),
            FrameReviewStep(self),
            PresetStep(self),
            AlignmentStep(self),
            BackgroundStep(self),
            PlaceholderStep(self, "Final export", "Review the final image and export PNG/TIFF outputs."),
            PlaceholderStep(self, "Done", "Open output folder or start a new project."),
        ]

        for step in self.steps:
            self.stack.addWidget(step)

        self.footer.back_button.clicked.connect(self.go_back)
        self.footer.next_button.clicked.connect(self.go_next)
        self.footer.save_button.clicked.connect(self.save_current_project)
        self.footer.cancel_button.clicked.connect(self.close)

        self.steps[0].new_card.clicked.connect(self.start_new_project)
        self.steps[0].open_card.clicked.connect(self.open_project_dialog)

        apply_dark_theme(self)
        self.go_to_step(0)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(16)

        icon_label = QLabel()
        icon_label.setObjectName("headerIcon")
        icon_label.setFixedSize(64, 64)
        icon_label.setAlignment(Qt.AlignCenter)

        header_icon_path = icons_dir() / "header_andromeda.png"
        if header_icon_path.exists():
            pixmap = QPixmap(str(header_icon_path))
            icon_label.setPixmap(
                pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

        title_box = QVBoxLayout()
        title_box.setSpacing(4)

        title = QLabel("Astronomical Image Reduction Tool")
        title.setObjectName("appTitle")

        subtitle = QLabel("Calibrate · Align · Stack · Color · Export")
        subtitle.setObjectName("appSubtitle")

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self.project_icon = QLabel("▱")
        self.project_icon.setObjectName("projectIcon")
        self.project_icon.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.project_label = QLabel("No project loaded")
        self.project_label.setObjectName("projectLabel")
        self.project_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        project_box = QHBoxLayout()
        project_box.setSpacing(10)
        project_box.addWidget(self.project_icon)
        project_box.addWidget(self.project_label)

        layout.addWidget(icon_label)
        layout.addLayout(title_box)
        layout.addStretch(1)
        layout.addLayout(project_box)

        return header

    def _build_wait_overlay(self) -> QFrame:
        overlay = QFrame(self.root)
        overlay.setObjectName("waitOverlay")
        overlay.hide()

        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)

        box = QFrame()
        box.setObjectName("waitOverlayBox")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(34, 24, 34, 24)
        box_layout.setSpacing(8)

        label = QLabel("Please wait")
        label.setObjectName("waitOverlayText")
        label.setAlignment(Qt.AlignCenter)

        detail = QLabel("Loading step...")
        detail.setObjectName("mutedText")
        detail.setAlignment(Qt.AlignCenter)

        box_layout.addWidget(label)
        box_layout.addWidget(detail)

        layout.addWidget(box, 0, Qt.AlignCenter)

        return overlay

    def resizeEvent(self, event):
        super().resizeEvent(event)

        if hasattr(self, "wait_overlay"):
            self.wait_overlay.setGeometry(self.root.rect())

    def show_wait_overlay(self):
        self.wait_overlay.setGeometry(self.root.rect())
        self.wait_overlay.raise_()
        self.wait_overlay.show()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()

    def hide_wait_overlay(self):
        self.wait_overlay.hide()

        if QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

        QApplication.processEvents()

    def ensure_project(self) -> ReductionProject:
        if self.project is None:
            self.project = ReductionProject()
        return self.project

    def start_new_project(self) -> None:
        self.project = ReductionProject()
        self.scan_result = None
        self.update_project_label()
        self.go_to_step(1)

    def open_project_dialog(self) -> None:
        start_dir = default_projects_dir()

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open AIRT project",
            str(start_dir),
            "AIRT Project (*.airt.json);;JSON Files (*.json);;All Files (*)",
        )

        if not path:
            return

        self.open_project_path(path)

    def open_project_path(self, path: str) -> None:
        try:
            self.project = load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not open project", str(exc))
            return

        self.scan_result = None
        self.mark_project_recent()
        self.update_project_label()
        self.footer.set_status(f"Project loaded: {path}")
        self.go_to_step(1)

    def mark_project_recent(self) -> None:
        if not self.project or not self.project.project_file:
            return

        display_name = self.project.object_name or Path(self.project.project_file).stem
        add_recent_project(self.project.project_file, display_name)

        welcome = self.steps[0]
        if hasattr(welcome, "refresh_recent_projects"):
            welcome.refresh_recent_projects()

    def update_project_label(self) -> None:
        if not self.project:
            self.project_label.setText("No project loaded")
            return

        if self.project.project_file:
            self.project_label.setText(Path(self.project.project_file).name)
        elif self.project.object_name:
            self.project_label.setText(self.project.object_name)
        else:
            self.project_label.setText("Unsaved project")

    def save_current_project(self) -> None:
        if not self.project:
            QMessageBox.information(self, "No project", "There is no project to save.")
            return

        if not self.project.project_file:
            QMessageBox.warning(
                self,
                "Project path not defined",
                "Go to the Folders step and define the object folder and object name first.",
            )
            return

        try:
            save_project(self.project)
        except Exception as exc:
            QMessageBox.critical(self, "Could not save project", str(exc))
            return

        self.mark_project_recent()
        self.update_project_label()
        self.footer.set_status(f"Project saved: {self.project.project_file}")

    def go_to_step(self, index: int) -> None:
        if index < 0 or index >= len(self.steps):
            return

        current_index = self.stack.currentIndex()
        show_wait = current_index != index and current_index >= 0

        if show_wait:
            self.show_wait_overlay()

        try:
            if current_index != index and 0 <= current_index < len(self.steps):
                current_step = self.steps[current_index]
                if hasattr(current_step, "on_leave"):
                    current_step.on_leave(index)

            self.stack.setCurrentIndex(index)
            self.sidebar.set_current_step(index)

            step = self.steps[index]
            if hasattr(step, "on_enter"):
                step.on_enter()
        finally:
            if show_wait:
                self.hide_wait_overlay()

    def go_back(self) -> None:
        self.go_to_step(self.stack.currentIndex() - 1)

    def go_next(self) -> None:
        step = self.steps[self.stack.currentIndex()]

        if hasattr(step, "on_next"):
            handled = step.on_next()
            if handled is False:
                return

        self.go_to_step(self.stack.currentIndex() + 1)

