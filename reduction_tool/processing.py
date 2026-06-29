from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.visualization import make_lupton_rgb

from .calibration import create_master_bias, create_master_flat, reduce_image
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

    return np.median(images, axis=0)


def subtract_sky_background(image: np.ndarray) -> np.ndarray:
    return np.clip(image - np.median(image), 0, None)


def create_available_channel_rgb(
    stacked: dict[str, np.ndarray],
    stretch: float,
    q_value: float,
) -> np.ndarray:
    if not stacked:
        raise ValueError("No stacked object images are available.")

    fallback = next(iter(stacked.values()))
    red = stacked.get("R", np.zeros_like(fallback))
    green = stacked.get("V", np.zeros_like(fallback))
    blue = stacked.get("B", np.zeros_like(fallback))

    return make_lupton_rgb(
        subtract_sky_background(red),
        subtract_sky_background(green),
        subtract_sky_background(blue),
        stretch=stretch,
        Q=q_value,
    )


def run_rgb_reduction(
    base_dir: Path,
    object_name: str = "object",
    object_folder: str = "object",
    stretch: float = 5,
    q_value: float = 8,
) -> ReductionResult:
    paths = ProjectPaths.from_base(base_dir, object_folder=object_folder)
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

    rgb = make_lupton_rgb(
        subtract_sky_background(stacked["R"]),
        subtract_sky_background(stacked["V"]),
        subtract_sky_background(stacked["B"]),
        stretch=stretch,
        Q=q_value,
    )

    output_file = paths.output_dir / f"{object_name}_reduced.png"
    return ReductionResult(rgb=rgb, stacked=stacked, output_file=output_file)


def run_reduction(
    paths: ProjectPaths,
    object_name: str = "object",
    stretch: float = 5,
    q_value: float = 8,
) -> ReductionResult:
    paths.output_dir.mkdir(parents=True, exist_ok=True)

    inventory = scan_project(paths)
    master_bias = create_master_bias(inventory.bias)

    available_bands = [
        band
        for band in ("R", "V", "B")
        if inventory.objects[band] and inventory.flats[band]
    ]
    if not available_bands:
        raise ValueError("No processable object filters were found. Need at least one of R, V or B with matching flats.")

    master_flats = {
        band: create_master_flat(inventory.flats[band], master_bias)
        for band in available_bands
    }

    reference_band = "V" if "V" in available_bands else available_bands[0]
    reference = reduce_image(
        inventory.objects[reference_band][0],
        master_bias,
        master_flats[reference_band],
    )
    stacked = {
        band: stack_band(inventory.objects[band], master_bias, master_flats[band], reference)
        for band in available_bands
    }

    rgb = create_available_channel_rgb(stacked, stretch, q_value)

    output_file = paths.output_dir / f"{object_name}_reduced.png"
    return ReductionResult(rgb=rgb, stacked=stacked, output_file=output_file)
