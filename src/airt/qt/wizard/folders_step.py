from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QFrame,
    QScrollArea,
)


class FolderSelectionStep(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self.fields: dict[str, QLineEdit] = {}

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
        root.setSpacing(22)

        title = QLabel("Project folders")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Select the object folder and calibration folders. "
            "The project file and output folder will be created automatically inside the object folder."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        root.addWidget(title)
        root.addWidget(subtitle)

        object_card = self._make_card("Object", minimum_height=215)
        object_grid = object_card.layout()

        self._add_path_row(object_grid, 0, "object_folder", "Object folder", browse=True)
        self._add_text_row(object_grid, 1, "object_name", "Object name")
        self._add_path_row(object_grid, 2, "project_file", "Project file", browse=False, readonly=True)

        calibration_card = self._make_card("Calibration", minimum_height=250)
        calibration_grid = calibration_card.layout()

        self._add_path_row(calibration_grid, 0, "bias_folder", "Bias", browse=True)
        self._add_path_row(calibration_grid, 1, "flats_folder", "Flats", browse=True)
        self._add_path_row(calibration_grid, 2, "dark_folder", "Dark", browse=True)
        self._add_path_row(calibration_grid, 3, "focus_folder", "Focus", browse=True)

        root.addWidget(object_card)
        root.addWidget(calibration_card)
        root.addStretch(1)

        outer.addWidget(scroll)

        self.fields["object_folder"].editingFinished.connect(self.infer_from_object_folder)
        self.fields["object_name"].editingFinished.connect(self.update_derived_paths)

    def _make_card(self, title_text: str, minimum_height: int) -> QFrame:
        card = QFrame()
        card.setObjectName("contentCard")
        card.setMinimumHeight(minimum_height)

        grid = QGridLayout(card)
        grid.setContentsMargins(28, 24, 28, 28)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 135)

        title = QLabel(title_text)
        title.setObjectName("sectionTitle")
        title.setMinimumHeight(36)
        grid.addWidget(title, 0, 0, 1, 3)

        return card

    def _add_text_row(self, grid: QGridLayout, row: int, key: str, label_text: str) -> None:
        actual_row = row + 1

        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        label.setMinimumHeight(40)

        edit = QLineEdit()
        edit.setObjectName("pathInput")
        edit.setMinimumHeight(40)

        self.fields[key] = edit

        grid.addWidget(label, actual_row, 0)
        grid.addWidget(edit, actual_row, 1, 1, 2)

    def _add_path_row(
        self,
        grid: QGridLayout,
        row: int,
        key: str,
        label_text: str,
        browse: bool,
        readonly: bool = False,
    ) -> None:
        actual_row = row + 1

        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        label.setMinimumHeight(40)

        edit = QLineEdit()
        edit.setObjectName("pathInput")
        edit.setMinimumHeight(40)
        edit.setReadOnly(readonly)

        self.fields[key] = edit

        grid.addWidget(label, actual_row, 0)
        grid.addWidget(edit, actual_row, 1)

        if browse:
            button = QPushButton("Browse")
            button.setMinimumWidth(120)
            button.setMinimumHeight(40)
            button.clicked.connect(lambda checked=False, k=key: self.browse_folder(k))
            grid.addWidget(button, actual_row, 2)
        else:
            spacer = QLabel("")
            spacer.setMinimumWidth(120)
            grid.addWidget(spacer, actual_row, 2)

    def browse_folder(self, key: str) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select folder")
        if not selected:
            return

        self.fields[key].setText(selected)

        if key == "object_folder":
            self.infer_from_object_folder()

    def infer_from_object_folder(self) -> None:
        object_folder_text = self.fields["object_folder"].text().strip()
        if not object_folder_text:
            return

        object_folder = Path(object_folder_text)
        object_name = object_folder.name

        if not self.fields["object_name"].text().strip():
            self.fields["object_name"].setText(object_name)

        project_root = object_folder.parent

        if not self.fields["bias_folder"].text().strip():
            self.fields["bias_folder"].setText(str(project_root / "calibration" / "bias"))

        if not self.fields["flats_folder"].text().strip():
            flat_folder = project_root / "calibration" / "flat"
            flats_folder = project_root / "calibration" / "flats"
            self.fields["flats_folder"].setText(str(flat_folder if flat_folder.exists() else flats_folder))

        if not self.fields["dark_folder"].text().strip():
            self.fields["dark_folder"].setText(str(project_root / "calibration" / "dark"))

        if not self.fields["focus_folder"].text().strip():
            self.fields["focus_folder"].setText(str(project_root / "calibration" / "focus"))

        self.update_derived_paths()

    def update_derived_paths(self) -> None:
        object_folder_text = self.fields["object_folder"].text().strip()
        object_name = self.fields["object_name"].text().strip()

        if not object_folder_text or not object_name:
            self.fields["project_file"].clear()
            return

        object_folder = Path(object_folder_text)
        self.fields["project_file"].setText(str(object_folder / f"{object_name}.airt.json"))

    def load_from_project(self) -> None:
        project = self.wizard.project
        if not project:
            return

        values = {
            "object_folder": project.object_folder,
            "object_name": project.object_name,
            "project_file": project.project_file,
            "bias_folder": project.bias_folder,
            "flats_folder": project.flats_folder,
            "dark_folder": project.dark_folder,
            "focus_folder": project.focus_folder,
        }

        for key, value in values.items():
            self.fields[key].setText(value or "")

    def save_to_project(self) -> None:
        project = self.wizard.ensure_project()

        object_folder_text = self.fields["object_folder"].text().strip()
        object_name = self.fields["object_name"].text().strip()

        object_folder = Path(object_folder_text) if object_folder_text else Path()

        project.object_folder = str(object_folder) if object_folder_text else ""
        project.object_name = object_name
        project.project_root = str(object_folder.parent) if object_folder_text else ""
        project.project_file = str(object_folder / f"{object_name}.airt.json") if object_folder_text and object_name else ""

        lights_folder = object_folder / "lights"
        project.lights_folder = str(lights_folder if lights_folder.exists() else object_folder) if object_folder_text else ""
        project.output_folder = str(object_folder / "output") if object_folder_text else ""

        project.bias_folder = self.fields["bias_folder"].text().strip()
        project.flats_folder = self.fields["flats_folder"].text().strip()
        project.dark_folder = self.fields["dark_folder"].text().strip()
        project.focus_folder = self.fields["focus_folder"].text().strip()

        project.update_timestamp()

    def on_enter(self):
        self.wizard.footer.back_button.setEnabled(True)
        self.wizard.footer.next_button.setEnabled(True)
        self.wizard.footer.set_status("Select the project folder structure.")
        self.load_from_project()

    def validate(self) -> bool:
        self.infer_from_object_folder()
        self.save_to_project()

        project = self.wizard.project

        if not project.object_folder:
            QMessageBox.warning(self, "Missing object folder", "Select the object folder.")
            return False

        if not project.object_name:
            QMessageBox.warning(self, "Missing object name", "Enter the object name.")
            return False

        required = {
            "Object folder": project.object_folder,
            "Lights folder": project.lights_folder,
            "Output folder": project.output_folder,
            "Bias folder": project.bias_folder,
            "Flats folder": project.flats_folder,
            "Dark folder": project.dark_folder,
            "Focus folder": project.focus_folder,
        }

        missing_values = [name for name, value in required.items() if not value]
        if missing_values:
            QMessageBox.warning(
                self,
                "Missing folders",
                "Fill these folders:\n\n" + "\n".join(missing_values),
            )
            return False

        missing_dirs = [path for path in required.values() if path and not Path(path).exists()]

        if missing_dirs:
            result = QMessageBox.question(
                self,
                "Create missing folders?",
                "Some folders do not exist. Create them now?\n\n" + "\n".join(missing_dirs),
            )

            if result != QMessageBox.Yes:
                return False

            for folder in missing_dirs:
                Path(folder).mkdir(parents=True, exist_ok=True)

        return True

    def on_next(self) -> bool:
        from airt.project import autosave_project

        if not self.validate():
            return False

        autosave_project(self.wizard.project)
        if hasattr(self.wizard, "mark_project_recent"):
            self.wizard.mark_project_recent()
        self.wizard.update_project_label()
        self.wizard.footer.set_status(f"Project saved: {self.wizard.project.project_file}")
        self.wizard.go_to_step(2)
        return False


