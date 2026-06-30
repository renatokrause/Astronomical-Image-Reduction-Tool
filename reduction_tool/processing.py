from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from astropy.visualization import make_lupton_rgb

from .calibration import create_master_bias, create_master_flat, reduce_image
from .io import scan_project
from .models import ProjectPaths


ALIGNMENT_NONE = "none"
ALIGNMENT_AUTOMATIC = "automatic"
ALIGNMENT_MANUAL = "manual"
ALIGNMENT_MODES = (ALIGNMENT_NONE, ALIGNMENT_AUTOMATIC, ALIGNMENT_MANUAL)
ProgressCallback = Callable[[float, str], None]


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


def apply_channel_offsets(
    stacked: dict[str, np.ndarray],
    offsets: dict[str, tuple[float, float]],
) -> dict[str, np.ndarray]:
    from scipy.ndimage import shift as ndi_shift

    shifted: dict[str, np.ndarray] = {}
    for band, image in stacked.items():
        dx, dy = offsets.get(band, (0.0, 0.0))
        if dx == 0 and dy == 0:
            shifted[band] = image
        else:
            shifted[band] = ndi_shift(image, shift=(dy, dx), order=1, mode="nearest")
    return shifted


def stack_band(
    object_files: list[Path],
    master_bias: np.ndarray,
    master_flat: np.ndarray,
    reference: np.ndarray,
    progress_callback: ProgressCallback | None = None,
    progress_start: float = 0.0,
    progress_end: float = 1.0,
    band: str = "",
) -> np.ndarray:
    if not object_files:
        raise ValueError("No object images were found for this filter.")

    images = []
    total = len(object_files)
    for index, file_path in enumerate(object_files, start=1):
        reduced = reduce_image(file_path, master_bias, master_flat)
        images.append(align_to_reference(reduced, reference))
        if progress_callback:
            fraction = index / total
            progress = progress_start + (progress_end - progress_start) * fraction
            label = f"Stacking {band}-band image {index} of {total}" if band else f"Stacking image {index} of {total}"
            progress_callback(progress, label)

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


def run_reduction(
    paths: ProjectPaths,
    object_name: str = "object",
    stretch: float = 5,
    q_value: float = 8,
    alignment_mode: str = ALIGNMENT_AUTOMATIC,
    progress_callback: ProgressCallback | None = None,
    object_file_selection: dict[str, list[Path]] | None = None,
) -> ReductionResult:
    paths.output_dir.mkdir(parents=True, exist_ok=True)

    if alignment_mode not in ALIGNMENT_MODES:
        raise ValueError(f"Unsupported alignment mode: {alignment_mode}.")

    def report(progress: float, message: str) -> None:
        if progress_callback:
            progress_callback(progress, message)

    report(2, "Scanning input folders")
    inventory = scan_project(paths)
    if object_file_selection is not None:
        for band, files in object_file_selection.items():
            if band in inventory.objects:
                inventory.objects[band] = list(files)
    report(8, "Creating master bias")
    master_bias = create_master_bias(inventory.bias)

    available_bands = [
        band
        for band in ("R", "V", "B")
        if inventory.objects[band] and inventory.flats[band]
    ]
    if not available_bands:
        raise ValueError("No processable object filters were found. Need at least one of R, V or B with matching flats.")

    master_flats = {}
    flat_start = 12.0
    flat_end = 28.0
    for index, band in enumerate(available_bands, start=1):
        report(flat_start + (flat_end - flat_start) * ((index - 1) / len(available_bands)), f"Creating {band}-band master flat")
        master_flats[band] = create_master_flat(inventory.flats[band], master_bias)
    report(flat_end, "Master flats ready")

    reference_band = "V" if "V" in available_bands else available_bands[0]
    report(30, f"Preparing {reference_band}-band alignment reference")
    reference = reduce_image(
        inventory.objects[reference_band][0],
        master_bias,
        master_flats[reference_band],
    )

    stacked = {}
    stack_start = 34.0
    stack_end = 76.0
    band_span = (stack_end - stack_start) / len(available_bands)
    for index, band in enumerate(available_bands):
        start = stack_start + band_span * index
        end = start + band_span
        report(start, f"Stacking {band}-band images")
        stacked[band] = stack_band(
            inventory.objects[band],
            master_bias,
            master_flats[band],
            reference,
            progress_callback=progress_callback,
            progress_start=start,
            progress_end=end,
            band=band,
        )

    channel_alignment: dict[str, ChannelAlignment]
    if alignment_mode in (ALIGNMENT_AUTOMATIC, ALIGNMENT_MANUAL) and len(stacked) > 1:
        report(82, "Aligning final color bands")
        stacked, channel_alignment = align_stacked_channels(stacked, reference_band)
    else:
        channel_alignment = {
            band: ChannelAlignment(method="not_requested")
            for band in stacked
        }

    report(90, "Composing RGB image")
    rgb = create_available_channel_rgb(stacked, stretch, q_value)
    report(96, "Preparing output image")

    output_file = paths.output_dir / f"{object_name}_reduced.png"
    return ReductionResult(
        rgb=rgb,
        stacked=stacked,
        output_file=output_file,
        alignment_mode=alignment_mode,
        alignment_reference=reference_band,
        channel_alignment=channel_alignment,
    )
