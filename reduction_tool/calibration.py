from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits


def read_fits_data(file_path: Path) -> np.ndarray:
    return np.asarray(fits.getdata(file_path), dtype=np.float64)


def create_master_bias(bias_files: list[Path]) -> np.ndarray:
    if not bias_files:
        raise ValueError("No bias files were found.")

    stack = [read_fits_data(file_path) for file_path in bias_files]
    return np.median(stack, axis=0)


def create_master_flat(flat_files: list[Path], master_bias: np.ndarray) -> np.ndarray:
    if not flat_files:
        raise ValueError("No flat files were found for this filter.")

    corrected = [read_fits_data(file_path) - master_bias for file_path in flat_files]
    master_flat = np.median(corrected, axis=0)
    median = np.median(master_flat)

    if median == 0:
        raise ValueError("Master flat has a zero median. Check the flat files.")

    return master_flat / median


def reduce_image(object_file: Path, master_bias: np.ndarray, master_flat: np.ndarray) -> np.ndarray:
    return (read_fits_data(object_file) - master_bias) / master_flat
