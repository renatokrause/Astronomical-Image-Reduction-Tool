from __future__ import annotations

from PySide6.QtWidgets import QWidget


def apply_dark_theme(widget: QWidget) -> None:
    widget.setStyleSheet(
        r'''
        QMainWindow {
            background-color: #0b1220;
            color: #e5eefc;
        }

        QWidget {
            color: #e5eefc;
            font-family: "Segoe UI", "Inter", Arial, sans-serif;
            font-size: 14px;
        }

        QLabel {
            background-color: transparent;
        }

        QScrollArea {
            background-color: #0b1220;
            border: none;
        }

        QScrollArea > QWidget > QWidget {
            background-color: #0b1220;
        }

        QScrollBar:vertical {
            background: #0b1220;
            width: 10px;
            margin: 0px;
        }

        QScrollBar::handle:vertical {
            background: #3a4b68;
            border-radius: 5px;
            min-height: 36px;
        }

        QScrollBar::handle:vertical:hover {
            background: #4da3ff;
        }

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0px;
        }

        #header {
            background-color: #07101d;
            border-bottom: 1px solid #24344f;
        }


        #headerIcon {
            background-color: transparent;
            border: none;
        }

        #projectIcon {
            color: #aebbd0;
            font-size: 28px;
        }

        #infoIcon {
            background-color: transparent;
            border: none;
        }
        #appTitle {
            font-size: 25px;
            font-weight: 700;
            color: #f7fbff;
        }

        #appSubtitle {
            font-size: 16px;
            color: #9fb0c8;
        }

        #projectLabel {
            font-size: 16px;
            color: #b8c6dc;
        }

        #stepSidebar {
            background-color: #0b1220;
        }

        #sidebarStep {
            color: #a8b6ce;
            background-color: transparent;
            border-radius: 8px;
            padding-left: 16px;
            font-size: 16px;
        }

        #sidebarStep[active="true"] {
            color: #ffffff;
            background-color: #16315c;
            border-left: 3px solid #3e90ff;
            font-weight: 600;
        }

        #contentCard,
        #emptyCard {
            background-color: #101a2d;
            border: 1px solid #263956;
            border-radius: 12px;
        }

        #heroCard {
            background-color: #101a2d;
            border: 1px solid #263956;
            border-radius: 16px;
        }

        #heroImage {
            background-color: #090f1b;
            border-radius: 22px;
            border: 1px solid #1e2f4c;
        }


        #heroBanner {
            border-radius: 18px;
            border: 1px solid #263956;
        }

        #heroBannerTitle {
            font-size: 40px;
            font-weight: 900;
            color: #ffffff;
        }

        #heroBannerSubtitle {
            font-size: 22px;
            font-weight: 700;
            color: #dfeaff;
        }

        #heroBannerDescription {
            font-size: 17px;
            color: #aebbd0;
        }
        #infoCard {
            background-color: #10233d;
            border: 1px solid #2f7ee6;
            border-radius: 10px;
        }

        #mutedText {
            color: #9eaec5;
            font-size: 14px;
        }

        #heroTitle {
            font-size: 36px;
            font-weight: 800;
            color: #ffffff;
        }

        #heroSubtitle {
            font-size: 17px;
            color: #cad5e7;
        }

        #sectionTitle {
            font-size: 20px;
            font-weight: 700;
            color: #f7fbff;
        }

        #pageTitle {
            font-size: 32px;
            font-weight: 800;
            color: #ffffff;
        }

        #pageSubtitle {
            font-size: 16px;
            color: #aebbd0;
        }

        #fieldLabel {
            color: #d7e2f3;
            font-weight: 600;
        }

        QLineEdit#pathInput {
            background-color: #0c1526;
            color: #f4f7fb;
            border: 1px solid #2b3d5a;
            border-radius: 6px;
            padding: 9px;
        }

        QLineEdit#pathInput:focus {
            border: 1px solid #4da3ff;
        }

        QPushButton {
            background-color: #14233a;
            color: #dce8fb;
            border: 1px solid #2a3d5e;
            border-radius: 8px;
            padding: 10px 16px;
        }

        QPushButton:hover {
            background-color: #1b3152;
            border-color: #3e90ff;
        }

        QPushButton:disabled {
            color: #64748b;
            background-color: #111827;
            border-color: #1f2937;
        }

        QPushButton#primaryButton {
            background-color: #2563eb;
            border-color: #3b82f6;
            color: white;
            font-weight: 700;
            min-width: 120px;
        }

        QPushButton#primaryButton:hover {
            background-color: #1d4ed8;
        }

        #actionCardPrimary {
    background-color: #0f192b;
    border: 1px solid #2a3d5e;
    border-radius: 14px;
}

#actionCardPrimary:hover {
    background-color: #14233a;
    border: 1px solid #3e90ff;
}

#actionCard {
    background-color: #0f192b;
    border: 1px solid #2a3d5e;
    border-radius: 14px;
}

#actionCard:hover {
    background-color: #14233a;
    border: 1px solid #3e90ff;
}

                        #actionCardIcon {
            background-color: transparent;
            border: none;
        }

        #actionCardTitle {
            color: #ffffff;
            font-size: 17px;
            font-weight: 700;
        }

        #actionCardDescription {
            color: #b9c7dc;
            font-size: 15px;
        }

        #actionCardArrow {
            color: #4da3ff;
            font-size: 42px;
            font-weight: 300;
        }

        #infoText {
            color: #c5d3e8;
            font-size: 15px;
        }

        #statusText {
            color: #9fb0c8;
        }
        

QFrame#waitOverlay {
    background-color: rgba(5, 10, 20, 145);
}

QFrame#waitOverlayBox {
    background-color: #101b2d;
    border: 1px solid #3e90ff;
    border-radius: 18px;
}

QLabel#waitOverlayText {
    color: #ffffff;
    font-size: 22px;
    font-weight: 700;
}

'''
    )
