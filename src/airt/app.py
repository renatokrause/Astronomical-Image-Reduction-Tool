from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from airt.qt.wizard.wizard_window import WizardWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Astronomical Image Reduction Tool")
    app.setOrganizationName("AIRT")

    icon_path = Path(__file__).resolve().parent / "resources" / "icons" / "app.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = WizardWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))

    window.showMaximized()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
