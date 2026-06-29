from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.visualization import make_lupton_rgb

from .calibration import create_master_bias, create_master_flat, median_stack, read_fits_data, reduce_image
from .io import scan_project
from .models import ProjectPaths


@dataclass
class ReductionResult:
    rgb: np.ndarray
    stacked: dict[str, np.ndarray]
    output_file: Path


def align_to_reference(image: np.ndarray, reference: np.ndarray) -> np.ndarray:
    try:
        import astroalign as aa

        aligned, _ = aa.register(image, reference)
        return aligned
    except Exception:
        return image


def crop_to_shape(image: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    target_rows, target_cols = shape
    rows, cols = image.shape

    if rows < target_rows or cols < target_cols:
        raise ValueError(
            f"Cannot crop image with shape {image.shape} to larger shape {shape}."
        )

    row_start = (rows - target_rows) // 2
    col_start = (cols - target_cols) // 2
    return image[row_start : row_start + target_rows, col_start : col_start + target_cols]


def crop_to_common_shape(images: list[np.ndarray]) -> list[np.ndarray]:
    if not images:
        return images

    min_rows = min(image.shape[0] for image in images)
    min_cols = min(image.shape[1] for image in images)
    common_shape = (min_rows, min_cols)
    return [crop_to_shape(image, common_shape) for image in images]


def stack_band(
    object_files: list[Path],
    master_bias: np.ndarray,
    master_flat: np.ndarray,
    reference: np.ndarray,
) -> np.ndarray:
    if not object_files:
        raise ValueError("No object images were found for this filter.")

    images = []
    for file_path in object_files:
        reduced = reduce_image(file_path, master_bias, master_flat)
        images.append(align_to_reference(reduced, reference))

    return median_stack(images, object_files, "calibrated object frames")


def stack_science_band(object_files: list[Path], reference: np.ndarray) -> np.ndarray:
    if not object_files:
        raise ValueError("No object images were found for this filter.")

    images = []
    for file_path in object_files:
        image = read_fits_data(file_path)
        images.append(align_to_reference(image, reference))

    images = crop_to_common_shape(images)
    return median_stack(images, object_files, "quick RGB object frames")


def subtract_sky_background(image: np.ndarray) -> np.ndarray:
    return np.clip(image - np.median(image), 0, None)


def run_rgb_reduction(
    base_dir: Path,
    object_name: str = "object",
    stretch: float = 5,
    q_value: float = 8,
) -> ReductionResult:
    paths = ProjectPaths.from_base(base_dir)
    paths.output_dir.mkdir(parents=True, exist_ok=True)

    inventory = scan_project(paths)
    master_bias = create_master_bias(inventory.bias)

    master_flats = {
        band: create_master_flat(inventory.flats[band], master_bias)
        for band in ("B", "V", "R")
    }

    if not inventory.objects["V"]:
        raise ValueError("At least one V-band image is required as the alignment reference.")

    reference = reduce_image(inventory.objects["V"][0], master_bias, master_flats["V"])
    stacked = {
        band: stack_band(inventory.objects[band], master_bias, master_flats[band], reference)
        for band in ("R", "V", "B")
    }

    red, green, blue = crop_to_common_shape([stacked["R"], stacked["V"], stacked["B"]])
    rgb = make_lupton_rgb(
        subtract_sky_background(red),
        subtract_sky_background(green),
        subtract_sky_background(blue),
        stretch=stretch,
        Q=q_value,
    )

    output_file = paths.output_dir / f"{object_name}_reduced.png"
    return ReductionResult(rgb=rgb, stacked=stacked, output_file=output_file)


def run_quick_rgb(
    base_dir: Path,
    object_name: str = "object",
    stretch: float = 5,
    q_value: float = 8,
) -> ReductionResult:
    paths = ProjectPaths.from_base(base_dir)
    paths.output_dir.mkdir(parents=True, exist_ok=True)

    inventory = scan_project(paths)
    missing_bands = [band for band in ("R", "V", "B") if not inventory.objects[band]]
    if missing_bands:
        missing = ", ".join(missing_bands)
        raise ValueError(f"Quick RGB mode requires object images for these filters: {missing}.")

    reference = read_fits_data(inventory.objects["V"][0])
    stacked = {
        band: stack_science_band(inventory.objects[band], reference)
        for band in ("R", "V", "B")
    }

    red, green, blue = crop_to_common_shape([stacked["R"], stacked["V"], stacked["B"]])
    rgb = make_lupton_rgb(
        subtract_sky_background(red),
        subtract_sky_background(green),
        subtract_sky_background(blue),
        stretch=stretch,
        Q=q_value,
    )

    output_file = paths.output_dir / f"{object_name}_quick_rgb.png"
    return ReductionResult(rgb=rgb, stacked=stacked, output_file=output_file)
