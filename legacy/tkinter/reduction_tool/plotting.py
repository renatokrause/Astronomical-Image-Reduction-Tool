from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np



def save_rgb_image(rgb: np.ndarray, output_file: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 10), frameon=False)
    ax.imshow(rgb, origin="lower")
    ax.axis("off")
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    fig.savefig(output_file, bbox_inches="tight", pad_inches=0, dpi=300)
    plt.close(fig)
