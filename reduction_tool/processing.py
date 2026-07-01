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
BACKGROUND_OFF = "off"
BACKGROUND_AUTOMATIC = "automatic"
BACKGROUND_VALID_FIELD_MASK = "valid_field_mask"
BACKGROUND_POLYNOMIAL = "polynomial"
BACKGROUND_MEDIAN_GRID = "median_grid"
BACKGROUND_PHOTUTILS = "photutils"
BACKGROUND_HYBRID = "hybrid"
BACKGROUND_CORRECTION_MODES = (
    BACKGROUND_OFF,
    BACKGROUND_AUTOMATIC,
    BACKGROUND_VALID_FIELD_MASK,
    BACKGROUND_POLYNOMIAL,
    BACKGROUND_MEDIAN_GRID,
    BACKGROUND_PHOTUTILS,
    BACKGROUND_HYBRID,
)
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
    background_correction: str = BACKGROUND_OFF
    background_mask_radius: float = 0.47
    background_mask_softness: float = 0.045
    background_outside_intensity: float = 0.0
    background_outside_level: float = 0.0
    background_band_corrections: dict[str, dict[str, float | str]] = field(default_factory=dict)


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


def estimate_smooth_background(image: np.ndarray) -> np.ndarray:
    from scipy.ndimage import gaussian_filter, zoom

    data = np.asarray(image, dtype=float)
    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    height, width = data.shape
    target_size = 96
    block_y = max(1, height // target_size)
    block_x = max(1, width // target_size)
    trimmed_height = max(block_y, (height // block_y) * block_y)
    trimmed_width = max(block_x, (width // block_x) * block_x)
    trimmed = data[:trimmed_height, :trimmed_width]
    low_resolution = np.median(
        trimmed.reshape(trimmed_height // block_y, block_y, trimmed_width // block_x, block_x),
        axis=(1, 3),
    )
    sigma = max(1.5, min(low_resolution.shape) * 0.08)
    low_resolution = gaussian_filter(low_resolution, sigma=sigma, mode="nearest")
    background = zoom(
        low_resolution,
        (height / low_resolution.shape[0], width / low_resolution.shape[1]),
        order=1,
    )
    return background[:height, :width]



def _safe_float_image(image: np.ndarray) -> np.ndarray:
    data = np.asarray(image, dtype=np.float32)
    return np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)


def _robust_sigma(data: np.ndarray) -> tuple[float, float]:
    values = np.asarray(data, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    sigma = 1.4826 * mad if mad > 0 else float(np.std(finite))
    return median, max(sigma, 1e-6)


def _normalise_preview(image: np.ndarray, low: float = 0.3, high: float = 99.7) -> np.ndarray:
    data = _safe_float_image(image)
    out = np.zeros_like(data, dtype=np.float32)
    if data.ndim == 2:
        lo, hi = np.percentile(data, [low, high])
        if hi <= lo:
            hi = lo + 1.0
        return np.clip((data - lo) / (hi - lo), 0, 1)
    for channel in range(data.shape[2]):
        plane = data[..., channel]
        lo, hi = np.percentile(plane, [low, high])
        if hi <= lo:
            hi = lo + 1.0
        out[..., channel] = np.clip((plane - lo) / (hi - lo), 0, 1)
    return out


def _dilate_mask(mask: np.ndarray, pixels: int) -> np.ndarray:
    if pixels <= 0:
        return mask.astype(bool)
    try:
        from scipy.ndimage import binary_dilation

        return binary_dilation(mask, iterations=int(pixels))
    except Exception:
        expanded = mask.astype(bool)
        for _ in range(int(pixels)):
            padded = np.pad(expanded, 1, mode="edge")
            expanded = (
                padded[1:-1, 1:-1]
                | padded[:-2, 1:-1]
                | padded[2:, 1:-1]
                | padded[1:-1, :-2]
                | padded[1:-1, 2:]
                | padded[:-2, :-2]
                | padded[:-2, 2:]
                | padded[2:, :-2]
                | padded[2:, 2:]
            )
        return expanded


def _auto_galaxy_geometry(luminance: np.ndarray) -> tuple[tuple[float, float], tuple[float, float], float]:
    height, width = luminance.shape
    try:
        from scipy.ndimage import gaussian_filter

        smoothed = gaussian_filter(luminance, sigma=max(4.0, min(height, width) / 80.0))
    except Exception:
        smoothed = luminance
    y, x = np.unravel_index(int(np.nanargmax(smoothed)), smoothed.shape)
    return (float(x), float(y)), (width * 0.22, height * 0.16), 0.0


def _ellipse_mask(
    shape: tuple[int, int],
    center: tuple[float, float],
    axes: tuple[float, float],
    angle_degrees: float,
) -> np.ndarray:
    height, width = shape
    center_x, center_y = center
    axis_a = max(1.0, float(axes[0]))
    axis_b = max(1.0, float(axes[1]))
    angle = np.deg2rad(float(angle_degrees))
    y, x = np.ogrid[:height, :width]
    dx = x - center_x
    dy = y - center_y
    rotated_x = dx * np.cos(angle) + dy * np.sin(angle)
    rotated_y = -dx * np.sin(angle) + dy * np.cos(angle)
    return (rotated_x / axis_a) ** 2 + (rotated_y / axis_b) ** 2 <= 1.0


def _build_background_mask(
    image_rgb: np.ndarray,
    star_sigma_threshold: float,
    star_mask_dilation_px: int,
    protect_galaxy: bool,
    galaxy_center: tuple[float, float] | None,
    galaxy_axes: tuple[float, float] | None,
    galaxy_angle: float,
) -> tuple[np.ndarray, dict[str, object], dict[str, np.ndarray]]:
    luminance = np.median(image_rgb, axis=2)
    median, sigma = _robust_sigma(luminance)
    star_mask = luminance > median + max(0.5, float(star_sigma_threshold)) * sigma
    star_mask = _dilate_mask(star_mask, int(star_mask_dilation_px))

    auto_center, auto_axes, auto_angle = _auto_galaxy_geometry(luminance)
    center = galaxy_center if galaxy_center is not None else auto_center
    axes = galaxy_axes if galaxy_axes is not None else auto_axes
    angle = galaxy_angle if galaxy_angle is not None else auto_angle
    galaxy_mask = _ellipse_mask(luminance.shape, center, axes, angle) if protect_galaxy else np.zeros_like(star_mask, dtype=bool)
    protected = star_mask | galaxy_mask

    used = ~protected
    if np.count_nonzero(used) < image_rgb.shape[0] * image_rgb.shape[1] * 0.05:
        protected = star_mask
        used = ~protected
    geometry = {
        "galaxy_center": center,
        "galaxy_axes": axes,
        "galaxy_angle": float(angle),
        "star_pixels": int(np.count_nonzero(star_mask)),
        "galaxy_pixels": int(np.count_nonzero(galaxy_mask)),
    }
    layers = {
        "stars": star_mask.astype(bool),
        "galaxy": galaxy_mask.astype(bool),
        "sky": used.astype(bool),
    }
    return protected, geometry, layers


def _sigma_clip_values(values: np.ndarray, sigma: float) -> np.ndarray:
    data = values[np.isfinite(values)]
    if data.size == 0:
        return data
    center, spread = _robust_sigma(data)
    return data[np.abs(data - center) <= max(0.5, float(sigma)) * spread]


def _median_grid_background(
    channel: np.ndarray,
    sky_mask: np.ndarray,
    grid_size: int,
    smoothing_sigma: float,
    sigma_clip: bool,
    sigma_clip_sigma: float,
) -> np.ndarray:
    from scipy.ndimage import gaussian_filter, zoom

    height, width = channel.shape
    grid = max(16, int(grid_size))
    samples_y = max(4, int(np.ceil(height / grid)))
    samples_x = max(4, int(np.ceil(width / grid)))
    low = np.empty((samples_y, samples_x), dtype=np.float32)
    global_values = channel[sky_mask]
    if sigma_clip:
        global_values = _sigma_clip_values(global_values, sigma_clip_sigma)
    global_median = float(np.median(global_values)) if global_values.size else float(np.median(channel))

    for row in range(samples_y):
        y0 = int(row * height / samples_y)
        y1 = int((row + 1) * height / samples_y)
        for col in range(samples_x):
            x0 = int(col * width / samples_x)
            x1 = int((col + 1) * width / samples_x)
            block = channel[y0:y1, x0:x1]
            block_mask = sky_mask[y0:y1, x0:x1]
            values = block[block_mask]
            if sigma_clip:
                values = _sigma_clip_values(values, sigma_clip_sigma)
            low[row, col] = float(np.median(values)) if values.size else global_median

    sigma = max(0.0, float(smoothing_sigma))
    if sigma > 0:
        low = gaussian_filter(low, sigma=sigma, mode="nearest")
    background = zoom(low, (height / low.shape[0], width / low.shape[1]), order=3)
    return background[:height, :width].astype(np.float32)


def _polynomial_background(
    channel: np.ndarray,
    sky_mask: np.ndarray,
    order: int,
    sigma_clip: bool,
    sigma_clip_sigma: float,
) -> np.ndarray:
    height, width = channel.shape
    y, x = np.indices(channel.shape, dtype=np.float32)
    xn = (x / max(1, width - 1)) * 2.0 - 1.0
    yn = (y / max(1, height - 1)) * 2.0 - 1.0
    values = channel[sky_mask]
    sample_x = xn[sky_mask]
    sample_y = yn[sky_mask]
    if sigma_clip and values.size:
        center, spread = _robust_sigma(values)
        keep = np.abs(values - center) <= max(0.5, float(sigma_clip_sigma)) * spread
        values = values[keep]
        sample_x = sample_x[keep]
        sample_y = sample_y[keep]
    if values.size < 16:
        return np.full_like(channel, float(np.median(channel)), dtype=np.float32)
    terms = []
    full_terms = []
    max_order = max(0, min(4, int(order)))
    for i in range(max_order + 1):
        for j in range(max_order + 1 - i):
            terms.append((sample_x ** i) * (sample_y ** j))
            full_terms.append((xn ** i) * (yn ** j))
    design = np.vstack(terms).T
    coeffs, *_ = np.linalg.lstsq(design, values, rcond=None)
    background = np.zeros_like(channel, dtype=np.float32)
    for coeff, term in zip(coeffs, full_terms):
        background += float(coeff) * term.astype(np.float32)
    return background


def _photutils_background(
    channel: np.ndarray,
    protected_mask: np.ndarray,
    grid_size: int,
    sigma_clip_sigma: float,
) -> np.ndarray:
    from astropy.stats import SigmaClip
    from photutils.background import Background2D, MedianBackground

    box = max(16, int(grid_size))
    sigma_clipper = SigmaClip(sigma=max(0.5, float(sigma_clip_sigma)))
    bkg = Background2D(
        channel,
        box_size=(box, box),
        filter_size=(3, 3),
        mask=protected_mask,
        sigma_clip=sigma_clipper,
        bkg_estimator=MedianBackground(),
    )
    return np.asarray(bkg.background, dtype=np.float32)


def _estimate_background_model(
    image_rgb: np.ndarray,
    protected_mask: np.ndarray,
    method: str,
    grid_size: int,
    smoothing_sigma: float,
    polynomial_order: int,
    sigma_clip: bool,
    sigma_clip_sigma: float,
) -> tuple[np.ndarray, str]:
    sky_mask = ~protected_mask
    background = np.zeros_like(image_rgb, dtype=np.float32)
    used_method = method
    for channel_index in range(3):
        channel = image_rgb[..., channel_index]
        if method == BACKGROUND_PHOTUTILS:
            try:
                background[..., channel_index] = _photutils_background(channel, protected_mask, grid_size, sigma_clip_sigma)
            except Exception:
                used_method = BACKGROUND_MEDIAN_GRID
                background[..., channel_index] = _median_grid_background(
                    channel, sky_mask, grid_size, smoothing_sigma, sigma_clip, sigma_clip_sigma
                )
        elif method == BACKGROUND_POLYNOMIAL:
            background[..., channel_index] = _polynomial_background(
                channel, sky_mask, polynomial_order, sigma_clip, sigma_clip_sigma
            )
        elif method in (BACKGROUND_MEDIAN_GRID, BACKGROUND_HYBRID, BACKGROUND_AUTOMATIC, BACKGROUND_VALID_FIELD_MASK):
            grid_model = _median_grid_background(channel, sky_mask, grid_size, smoothing_sigma, sigma_clip, sigma_clip_sigma)
            if method == BACKGROUND_HYBRID:
                poly_model = _polynomial_background(channel, sky_mask, polynomial_order, sigma_clip, sigma_clip_sigma)
                background[..., channel_index] = 0.75 * grid_model + 0.25 * poly_model
            else:
                background[..., channel_index] = grid_model
        else:
            background[..., channel_index] = np.median(channel[sky_mask]) if np.any(sky_mask) else np.median(channel)
    return background, used_method


def remove_background_gradient(
    image_rgb,
    method="hybrid",
    star_sigma_threshold=3.0,
    star_mask_dilation_px=3,
    protect_galaxy=True,
    galaxy_center=None,
    galaxy_axes=None,
    galaxy_angle=0.0,
    grid_size=128,
    smoothing_sigma=3.0,
    polynomial_order=2,
    sigma_clip=True,
    sigma_clip_sigma=3.0,
    correction_strength=0.8,
    neutralize_background=True,
    black_point_percentile=0.3,
    avoid_clipping=True,
    output_floor_mode="percentile_shift",
    debug=False,
):
    image = _safe_float_image(image_rgb)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("image_rgb must be an RGB array with shape (height, width, 3).")
    method = BACKGROUND_HYBRID if method == "hybrid" else str(method)
    if method == BACKGROUND_OFF:
        background = np.zeros_like(image, dtype=np.float32)
        corrected = image.copy()
        mask = np.zeros(image.shape[:2], dtype=bool)
        residual = corrected.copy()
        stats = {"method": BACKGROUND_OFF, "sky_pixels_used_percent": 100.0}
        return {"corrected": corrected, "background_model": background, "mask": mask, "residual": residual, "stats": stats, "debug_images": {}}

    protected_mask, geometry, mask_layers = _build_background_mask(
        image,
        star_sigma_threshold,
        star_mask_dilation_px,
        bool(protect_galaxy),
        galaxy_center,
        galaxy_axes,
        galaxy_angle,
    )
    sky_mask = ~protected_mask
    background_before = np.array([
        float(np.median(image[..., channel][sky_mask])) if np.any(sky_mask) else float(np.median(image[..., channel]))
        for channel in range(3)
    ])
    background_model, used_method = _estimate_background_model(
        image,
        protected_mask,
        method,
        grid_size,
        smoothing_sigma,
        polynomial_order,
        bool(sigma_clip),
        sigma_clip_sigma,
    )
    reference = np.array([
        float(np.median(background_model[..., channel][sky_mask])) if np.any(sky_mask) else float(np.median(background_model[..., channel]))
        for channel in range(3)
    ], dtype=np.float32)
    strength = min(1.0, max(0.0, float(correction_strength)))
    corrected = image - strength * (background_model - reference.reshape(1, 1, 3))

    if neutralize_background and np.any(sky_mask):
        sky_medians = np.array([float(np.median(corrected[..., channel][sky_mask])) for channel in range(3)], dtype=np.float32)
        neutral = float(np.median(sky_medians))
        corrected = corrected - (sky_medians - neutral).reshape(1, 1, 3)

    output_floor_mode = str(output_floor_mode)

    if black_point_percentile is not None and output_floor_mode == "percentile_shift":
        percentile = min(10.0, max(0.0, float(black_point_percentile)))
        if percentile > 0:
            black_points = np.array([
                float(np.percentile(corrected[..., channel][sky_mask], percentile)) if np.any(sky_mask) else float(np.percentile(corrected[..., channel], percentile))
                for channel in range(3)
            ], dtype=np.float32)
            corrected = corrected - black_points.reshape(1, 1, 3)

    clipped_low = int(np.count_nonzero(corrected < 0))
    if avoid_clipping:
        floor = 0.0
        corrected = np.where(corrected < floor, floor + np.log1p(np.maximum(-corrected, 0)) * 0.0, corrected)
    else:
        corrected = np.clip(corrected, 0, None)
    residual = corrected - np.array([
        float(np.median(corrected[..., channel][sky_mask])) if np.any(sky_mask) else float(np.median(corrected[..., channel]))
        for channel in range(3)
    ], dtype=np.float32).reshape(1, 1, 3)
    background_after = np.array([
        float(np.median(corrected[..., channel][sky_mask])) if np.any(sky_mask) else float(np.median(corrected[..., channel]))
        for channel in range(3)
    ])
    clipped_total = clipped_low + int(np.count_nonzero(~np.isfinite(corrected)))
    total_values = int(np.prod(corrected.shape))
    stats = {
        "method": used_method,
        "parameters": {
            "star_sigma_threshold": float(star_sigma_threshold),
            "star_mask_dilation_px": int(star_mask_dilation_px),
            "protect_galaxy": bool(protect_galaxy),
            "grid_size": int(grid_size),
            "smoothing_sigma": float(smoothing_sigma),
            "polynomial_order": int(polynomial_order),
            "sigma_clip": bool(sigma_clip),
            "sigma_clip_sigma": float(sigma_clip_sigma),
            "correction_strength": strength,
            "neutralize_background": bool(neutralize_background),
            "black_point_percentile": float(black_point_percentile),
            "avoid_clipping": bool(avoid_clipping),
            "output_floor_mode": output_floor_mode,
        },
        "sky_pixels_used_percent": float(np.count_nonzero(sky_mask) * 100.0 / sky_mask.size),
        "background_median_before": background_before.tolist(),
        "background_median_after": background_after.tolist(),
        "clipped_pixels_percent": float(clipped_total * 100.0 / max(1, total_values)),
        **geometry,
    }
    debug_images = {}
    if debug:
        mask_rgb = np.zeros((*protected_mask.shape, 3), dtype=np.float32)
        mask_rgb[..., 1] = mask_layers["sky"].astype(np.float32) * 0.55
        mask_rgb[..., 0] = mask_layers["stars"].astype(np.float32)
        mask_rgb[..., 2] = mask_layers["galaxy"].astype(np.float32)
        mask_rgb[..., 0] = np.maximum(mask_rgb[..., 0], mask_layers["galaxy"].astype(np.float32) * 0.85)
        debug_images = {
            "original_preview": _normalise_preview(image),
            "mask": mask_rgb,
            "background_model": _normalise_preview(background_model),
            "corrected_linear": _normalise_preview(corrected),
            "corrected_stretched": _normalise_preview(corrected, 1.0, 99.5),
            "residual_background": _normalise_preview(residual, 1.0, 99.0),
        }
    return {
        "corrected": corrected.astype(np.float32),
        "background_model": background_model.astype(np.float32),
        "mask": protected_mask,
        "residual": residual.astype(np.float32),
        "stats": stats,
        "debug_images": debug_images,
        "mask_layers": mask_layers,
    }
def apply_automatic_background_correction(stacked: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    corrected: dict[str, np.ndarray] = {}
    for band, image in stacked.items():
        background = estimate_smooth_background(image)
        corrected[band] = np.clip(image - background, 0, None)
    return corrected


def valid_field_mask(
    shape: tuple[int, ...],
    radius_fraction: float = 0.47,
    softness_fraction: float = 0.045,
    outside_intensity: float = 0.0,
    outside_level: float = 0.0,
) -> np.ndarray:
    height, width = int(shape[0]), int(shape[1])
    y, x = np.ogrid[:height, :width]
    center_y = (height - 1) / 2.0
    center_x = (width - 1) / 2.0
    radius_fraction = min(0.95, max(0.10, float(radius_fraction)))
    softness_fraction = min(0.50, max(0.001, float(softness_fraction)))
    outside_intensity = min(1.0, max(0.0, float(outside_intensity)))
    outside_level = min(1.0, max(0.0, float(outside_level)))
    radius = min(height, width) * radius_fraction
    feather = max(1.0, min(height, width) * softness_fraction)
    distance = np.sqrt((x - center_x) ** 2 + (y - center_y) ** 2)
    mask = np.clip((radius + feather - distance) / feather, 0.0, 1.0)
    smooth_mask = mask * mask * (3.0 - 2.0 * mask)
    outside_mask = outside_level + (1.0 - outside_level) * smooth_mask
    return (1.0 - outside_intensity) + outside_intensity * outside_mask


def apply_valid_field_mask(
    stacked: dict[str, np.ndarray],
    radius_fraction: float = 0.47,
    softness_fraction: float = 0.045,
    outside_intensity: float = 0.0,
    outside_level: float = 0.0,
) -> dict[str, np.ndarray]:
    if not stacked:
        return stacked
    first_image = next(iter(stacked.values()))
    mask = valid_field_mask(first_image.shape, radius_fraction, softness_fraction, outside_intensity, outside_level)
    return {band: np.asarray(image) * mask for band, image in stacked.items()}


def apply_background_correction(
    stacked: dict[str, np.ndarray],
    background_correction: str,
    mask_radius: float = 0.47,
    mask_softness: float = 0.045,
    outside_intensity: float = 0.0,
    outside_level: float = 0.0,
) -> dict[str, np.ndarray]:
    if background_correction == BACKGROUND_OFF:
        return stacked
    if background_correction == BACKGROUND_AUTOMATIC:
        return apply_automatic_background_correction(stacked)
    if background_correction == BACKGROUND_VALID_FIELD_MASK:
        return apply_valid_field_mask(stacked, mask_radius, mask_softness, outside_intensity, outside_level)
    raise ValueError(f"Unsupported background correction mode: {background_correction}.")


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
    background_correction: str = BACKGROUND_OFF,
    mask_radius: float = 0.47,
    mask_softness: float = 0.045,
    outside_intensity: float = 0.0,
    outside_level: float = 0.0,
) -> ReductionResult:
    paths.output_dir.mkdir(parents=True, exist_ok=True)

    if alignment_mode not in ALIGNMENT_MODES:
        raise ValueError(f"Unsupported alignment mode: {alignment_mode}.")
    if background_correction not in BACKGROUND_CORRECTION_MODES:
        raise ValueError(f"Unsupported background correction mode: {background_correction}.")

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

    if background_correction != BACKGROUND_OFF:
        report(88, "Applying background correction")
        stacked = apply_background_correction(stacked, background_correction, mask_radius, mask_softness, outside_intensity, outside_level)

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
        background_correction=background_correction,
        background_mask_radius=mask_radius,
        background_mask_softness=mask_softness,
        background_outside_intensity=outside_intensity,
        background_outside_level=outside_level,
    )
