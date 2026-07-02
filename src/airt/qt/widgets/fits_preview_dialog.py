from __future__ import annotations

from pathlib import Path
import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QPushButton,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QMessageBox,
    QSplitter,
    QWidget,
    QAbstractItemView,
)


class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)


class FitsPreviewDialog(QDialog):
    def __init__(self, files, parent=None):
        super().__init__(parent)

        self.files = list(files)
        self.current_pixmap_item: QGraphicsPixmapItem | None = None

        self.setWindowTitle("FITS preview")
        self.resize(1200, 780)
        self.setWindowState(self.windowState() | Qt.WindowMaximized)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top = QHBoxLayout()

        self.info_label = QLabel("Select one or more files to preview.")
        self.info_label.setWordWrap(True)

        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self.fit_to_view)

        self.zoom_in_button = QPushButton("Zoom in")
        self.zoom_in_button.clicked.connect(lambda: self.view.scale(1.25, 1.25))

        self.zoom_out_button = QPushButton("Zoom out")
        self.zoom_out_button.clicked.connect(lambda: self.view.scale(0.8, 0.8))

        top.addWidget(self.info_label, 1)
        top.addWidget(self.fit_button)
        top.addWidget(self.zoom_in_button)
        top.addWidget(self.zoom_out_button)

        root.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        list_buttons = QHBoxLayout()

        self.select_all_button = QPushButton("Select all")
        self.select_all_button.clicked.connect(self.select_all_files)

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_selection)

        list_buttons.addWidget(self.select_all_button)
        list_buttons.addWidget(self.clear_button)

        self.file_list = QListWidget()
        self.file_list.setMinimumWidth(360)
        self.file_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.file_list.itemSelectionChanged.connect(self.load_selected_files)

        for item in self.files:
            band = item.band if item.band != "-" else "None"
            label = f"{item.kind.upper()}  {band}  —  {Path(item.path).name}"
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.UserRole, item.path)
            self.file_list.addItem(list_item)

        left_layout.addLayout(list_buttons)
        left_layout.addWidget(self.file_list, 1)

        self.scene = QGraphicsScene(self)
        self.view = ZoomableGraphicsView()
        self.view.setScene(self.scene)
        self.view.setBackgroundBrush(Qt.black)

        splitter.addWidget(left_panel)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)

        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.accept)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        bottom.addWidget(self.apply_button)
        bottom.addWidget(self.cancel_button)

        root.addLayout(bottom)

        if self.files:
            self.select_all_files()

    def select_all_files(self):
        self.file_list.selectAll()

    def clear_selection(self):
        self.file_list.clearSelection()
        self.scene.clear()
        self.current_pixmap_item = None
        self.info_label.setText("No files selected.")

    def selected_paths(self) -> set[str]:
        return {
            item.data(Qt.UserRole)
            for item in self.file_list.selectedItems()
        }

    def selected_file_infos(self):
        selected_paths = self.selected_paths()

        return [
            info
            for info in self.files
            if info.path in selected_paths
        ]

    def load_selected_files(self):
        selected = self.selected_file_infos()

        if not selected:
            self.scene.clear()
            self.current_pixmap_item = None
            self.info_label.setText("No files selected.")
            return

        try:
            image = self.load_preview_image(selected)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Preview failed",
                f"Could not preview selected files:\n\n{exc}",
            )
            return

        pixmap = QPixmap.fromImage(image)

        self.scene.clear()
        self.current_pixmap_item = self.scene.addPixmap(pixmap)
        self.scene.setSceneRect(self.current_pixmap_item.boundingRect())

        if len(selected) == 1:
            info = selected[0]
            path = Path(info.path)
            size_text = (
                f"{info.naxis1} × {info.naxis2}"
                if info.naxis1 and info.naxis2
                else f"{pixmap.width()} × {pixmap.height()}"
            )
            exposure = "-" if info.exptime is None else f"{info.exptime:g}s"
            band = info.band if info.band != "-" else "None"

            self.info_label.setText(
                f"{path.name} | Type: {info.kind.upper()} | Band: {band} "
                f"| Exposure: {exposure} | Size: {size_text}"
            )
        else:
            kinds = sorted({info.kind.upper() for info in selected})
            bands = sorted({info.band if info.band != "-" else "None" for info in selected})
            self.info_label.setText(
                f"Combined preview of {len(selected)} selected files | "
                f"Types: {', '.join(kinds)} | Bands: {', '.join(bands)} | Combination: median"
            )

        self.fit_to_view()

    def load_preview_image(self, selected) -> QImage:
        arrays = []
        reference_shape = None

        for info in selected:
            data = self.load_fits_array(Path(info.path))

            if reference_shape is None:
                reference_shape = data.shape

            if data.shape != reference_shape:
                raise ValueError(
                    "Selected files have different dimensions. "
                    "Preview combination requires files with the same image size."
                )

            arrays.append(data)

        if not arrays:
            raise ValueError("No files selected.")

        if len(arrays) == 1:
            combined = arrays[0]
        else:
            combined = np.nanmedian(np.stack(arrays, axis=0), axis=0)

        return self.array_to_qimage(combined)

    def load_fits_array(self, path: Path) -> np.ndarray:
        from astropy.io import fits

        data = fits.getdata(path, 0)
        data = np.asarray(data)

        if data.ndim > 2:
            data = np.squeeze(data)

            if data.ndim > 2:
                data = data[0]

        if data.ndim != 2:
            raise ValueError(f"Unsupported FITS image dimensions for {path.name}: {data.shape}")

        return data.astype(np.float32, copy=False)

    def array_to_qimage(self, data: np.ndarray) -> QImage:
        finite = np.isfinite(data)
        if not np.any(finite):
            raise ValueError("Image has no finite pixels.")

        valid = data[finite]

        low, high = np.percentile(valid, [1, 99.5])

        if high <= low:
            low = float(np.min(valid))
            high = float(np.max(valid))

        if high <= low:
            high = low + 1.0

        stretched = (data - low) / (high - low)
        stretched = np.clip(stretched, 0, 1)
        stretched[~finite] = 0

        image8 = (stretched * 255).astype(np.uint8)
        image8 = np.ascontiguousarray(image8)

        height, width = image8.shape
        bytes_per_line = image8.strides[0]

        return QImage(
            image8.data,
            width,
            height,
            bytes_per_line,
            QImage.Format_Grayscale8,
        ).copy()

    def fit_to_view(self):
        if not self.current_pixmap_item:
            return

        self.view.resetTransform()
        self.view.fitInView(self.current_pixmap_item, Qt.KeepAspectRatio)
