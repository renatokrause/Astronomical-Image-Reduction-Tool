from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from astropy.visualization import make_lupton_rgb

from .calibration import create_master_bias, create_master_flat, reduce_image
from .io import scan_project
from .models import ProjectPaths


ALIGNMENT_NONE = "none"
ALIGNMENT_AUTOMATIC = "automatic"
ALIGNMENT_MODES = (ALIGNMENT_NONE, ALIGNMENT_AUTOMATIC)


@dataclass
class ChannelAlignment:
    method: str
    dx: float = 0.0
    dy: float = 0.0


@dataclass
class ReductionResult:
    rgb: np.ndarray
    stacked: dict[str, np.ndarray]
    output_file: Path
    alignment_mode: str = ALIGNMENT_AUTOMATIC
    alignment_reference: str | None = None
    channel_alignment: dict[str, ChannelAlignment] = field(default_factory=dict)


def align_to_reference(image: np.ndarray, reference: np.ndarray) -> np.ndarray:
    try:
        import astroalign as aa

        aligned, _ = aa.register(image, reference)
        return aligned
    except Exception:
        return image


def _registration_image(image: np.ndarray) -> np.ndarray:
    data = np.asarray(image, dtype=float)
    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    data = data - np.nanmedian(data)
    high = np.nanpercentile(data, 99.5)
    if high > 0:
        data = data / high
    return np.clip(data, 0, 1)


def align_channel_to_reference(
    image: np.ndarray,
    reference: np.ndarray,
) -> tuple[np.ndarray, ChannelAlignment]:
    try:
        import astroalign as aa

        aligned, _ = aa.register(image, reference)
        return aligned, ChannelAlignment(method="astroalign")
    except Exception:
        pass

    try:
        from scipy.ndimage import shift as ndi_shift
        from skimage.registration import phase_cross_correlation

        shift, _error, _phase = phase_cross_correlation(
            _registration_image(reference),
            _registration_image(image),
            upsample_factor=10,
        )
        aligned = ndi_shift(image, shift=shift, order=1, mode="nearest")
        dy, dx = float(shift[0]), float(shift[1])
        return aligned, ChannelAlignment(method="phase_cross_correlation", dx=dx, dy=dy)
    except Exception:
        return image, ChannelAlignment(method="not_aligned")


def align_stacked_channels(
    stacked: dict[str, np.ndarray],
    reference_band: str,
) -> tuple[dict[str, np.ndarray], dict[str, ChannelAlignment]]:
    if reference_band not in stacked:
        return stacked, {}

    reference = stacked[reference_band]
    aligned: dict[str, np.ndarray] = {}
    metadata: dict[str, ChannelAlignment] = {}

    for band, image in stacked.items():
        if band == reference_band:
            aligned[band] = image
            metadata[band] = ChannelAlignment(method="reference")
            continue

        aligned_image, alignment = align_channel_to_reference(image, reference)
        aligned[band] = aligned_image
        metadata[band] = alignment

    return aligned, metadata


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
    stacked, channel_alignment = align_stacked_channels(stacked, "V")

    rgb = create_available_channel_rgb(stacked, stretch, q_value)

    output_file = paths.output_dir / f"{object_name}_reduced.png"
    return ReductionResult(
        rgb=rgb,
        stacked=stacked,
        output_file=output_file,
        alignment_mode=ALIGNMENT_AUTOMATIC,
        alignment_reference="V",
        channel_alignment=channel_alignment,
    )


def run_reduction(
    paths: ProjectPaths,
    object_name: str = "object",
    stretch: float = 5,
    q_value: float = 8,
    alignment_mode: str = ALIGNMENT_AUTOMATIC,
) -> ReductionResult:
    paths.output_dir.mkdir(parents=True, exist_ok=True)

    if alignment_mode not in ALIGNMENT_MODES:
        raise ValueError(f"Unsupported alignment mode: {alignment_mode}.")

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

    channel_alignment: dict[str, ChannelAlignment] = {}
    if alignment_mode == ALIGNMENT_AUTOMATIC and len(stacked) > 1:
        stacked, channel_alignment = align_stacked_channels(stacked, reference_band)
    else:
        channel_alignment = {
            band: ChannelAlignment(method="not_requested")
            for band in stacked
        }

    rgb = create_available_channel_rgb(stacked, stretch, q_value)

    output_file = paths.output_dir / f"{object_name}_reduced.png"
    return ReductionResult(
        rgb=rgb,
        stacked=stacked,
        output_file=output_file,
        alignment_mode=alignment_mode,
        alignment_reference=reference_band,
        channel_alignment=channel_alignment,
    )
