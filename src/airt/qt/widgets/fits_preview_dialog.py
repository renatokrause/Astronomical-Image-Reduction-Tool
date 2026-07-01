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
    QLabel,
    QPushButton,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QMessageBox,
    QSplitter,
    QWidget,
)


class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHints(self.renderHints())

    def wheelEvent(self, event: QWheelEvent):
        if event.angleDelta().y() > 0:
            factor = 1.25
        else:
            factor = 0.8

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

        self.info_label = QLabel("Select a file to preview.")
        self.info_label.setWordWrap(True)

        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self.fit_to_view)

        self.zoom_in_button = QPushButton("Zoom in")
        self.zoom_in_button.clicked.connect(lambda: self.view.scale(1.25, 1.25))

        self.zoom_out_button = QPushButton("Zoom out")
        self.zoom_out_button.clicked.connect(lambda: self.view.scale(0.8, 0.8))

        self.zoom_100_button = QPushButton("100%")
        self.zoom_100_button.clicked.connect(self.zoom_100)

        top.addWidget(self.info_label, 1)
        top.addWidget(self.fit_button)
        top.addWidget(self.zoom_100_button)
        top.addWidget(self.zoom_in_button)
        top.addWidget(self.zoom_out_button)

        root.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)

        self.file_list = QListWidget()
        self.file_list.setMinimumWidth(320)

        for item in self.files:
            label = f"{item.kind.upper()}  {item.band}  —  {Path(item.path).name}"
            self.file_list.addItem(label)

        self.file_list.currentRowChanged.connect(self.load_selected_file)

        self.scene = QGraphicsScene(self)
        self.view = ZoomableGraphicsView()
        self.view.setScene(self.scene)
        self.view.setBackgroundBrush(Qt.black)

        splitter.addWidget(self.file_list)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        bottom.addWidget(close_button)

        root.addLayout(bottom)

        if self.files:
            self.file_list.setCurrentRow(0)

    def load_selected_file(self, row: int):
        if row < 0 or row >= len(self.files):
            return

        info = self.files[row]
        path = Path(info.path)

        try:
            image = self.load_fits_as_qimage(path)
        except Exception as exc:
            QMessageBox.warning(self, "Preview failed", f"Could not preview file:\n\n{path}\n\n{exc}")
            return

        pixmap = QPixmap.fromImage(image)

        self.scene.clear()
        self.current_pixmap_item = self.scene.addPixmap(pixmap)
        self.scene.setSceneRect(self.current_pixmap_item.boundingRect())

        size_text = f"{info.naxis1} × {info.naxis2}" if info.naxis1 and info.naxis2 else f"{pixmap.width()} × {pixmap.height()}"
        exposure = "-" if info.exptime is None else f"{info.exptime:g}s"

        self.info_label.setText(
            f"{path.name} | Type: {info.kind.upper()} | Band: {info.band} | Exposure: {exposure} | Size: {size_text}"
        )

        self.fit_to_view()

    def load_fits_as_qimage(self, path: Path) -> QImage:
        from astropy.io import fits

        data = fits.getdata(path, 0)

        data = np.asarray(data)

        if data.ndim > 2:
            data = np.squeeze(data)

            if data.ndim > 2:
                data = data[0]

        data = data.astype(np.float32, copy=False)

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

    def zoom_100(self):
        self.view.resetTransform()

