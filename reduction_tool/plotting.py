from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from astropy.visualization import ImageNormalize, ZScaleInterval

from .calibration import reduce_image


def save_rgb_image(rgb: np.ndarray, output_file: Path, title: str, caption: str = "") -> None:
    fig, ax = plt.subplots(figsize=(12, 10))
    ax.imshow(rgb, origin="lower")
    ax.set_title(title)
    ax.axis("off")

    if caption:
        ax.text(
            0.95,
            0.05,
            caption,
            transform=ax.transAxes,
            fontsize=10,
            color="white",
            verticalalignment="bottom",
            horizontalalignment="right",
            bbox={
                "boxstyle": "round,pad=0.5",
                "facecolor": "black",
                "alpha": 0.25,
                "edgecolor": "none",
            },
        )

    fig.savefig(output_file, bbox_inches="tight", dpi=300)
    plt.close(fig)


def save_preview(
    object_file: Path,
    master_bias: np.ndarray,
    master_flat: np.ndarray,
    output_file: Path,
) -> None:
    image = reduce_image(object_file, master_bias, master_flat)
    norm = ImageNormalize(image, interval=ZScaleInterval())

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(image, origin="lower", cmap="gray", norm=norm)
    ax.set_title(object_file.name)
    ax.axis("off")
    fig.savefig(output_file, bbox_inches="tight", dpi=150)
    plt.close(fig)
