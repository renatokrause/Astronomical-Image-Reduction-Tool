from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits


def read_fits_data(file_path: Path) -> np.ndarray:
    data = np.asarray(fits.getdata(file_path), dtype=np.float64)
    data = np.squeeze(data)

    if data.ndim != 2:
        raise ValueError(
            f"{file_path.name} is not a 2D FITS image after loading. "
            f"Detected shape: {data.shape}."
        )

    return data


def median_stack(images: list[np.ndarray], files: list[Path], label: str) -> np.ndarray:
    if not images:
        raise ValueError(f"No images were provided for {label}.")

    expected_shape = images[0].shape
    for image, file_path in zip(images, files):
        if image.shape != expected_shape:
            raise ValueError(
                f"Cannot stack {label}: image dimensions do not match. "
                f"Expected {expected_shape}, but {file_path.name} has {image.shape}."
            )

    return np.median(np.stack(images, axis=0), axis=0)


def create_master_bias(bias_files: list[Path]) -> np.ndarray:
    if not bias_files:
        raise ValueError("No bias files were found.")

    stack = [read_fits_data(file_path) for file_path in bias_files]
    return median_stack(stack, bias_files, "bias frames")


def create_master_flat(flat_files: list[Path], master_bias: np.ndarray) -> np.ndarray:
    if not flat_files:
        raise ValueError("No flat files were found for this filter.")

    corrected = []
    for file_path in flat_files:
        flat = read_fits_data(file_path)
        if flat.shape != master_bias.shape:
            raise ValueError(
                f"Cannot calibrate flat {file_path.name}: flat shape {flat.shape} "
                f"does not match master bias shape {master_bias.shape}."
            )
        corrected.append(flat - master_bias)

    master_flat = median_stack(corrected, flat_files, "flat frames")
    median = np.median(master_flat)

    if median == 0:
        raise ValueError("Master flat has a zero median. Check the flat files.")

    return master_flat / median


def reduce_image(object_file: Path, master_bias: np.ndarray, master_flat: np.ndarray) -> np.ndarray:
    image = read_fits_data(object_file)
    if image.shape != master_bias.shape:
        raise ValueError(
            f"Cannot reduce {object_file.name}: object image shape {image.shape} "
            f"does not match master bias shape {master_bias.shape}."
        )
    if image.shape != master_flat.shape:
        raise ValueError(
            f"Cannot reduce {object_file.name}: object image shape {image.shape} "
            f"does not match master flat shape {master_flat.shape}."
        )

    return (image - master_bias) / master_flat
