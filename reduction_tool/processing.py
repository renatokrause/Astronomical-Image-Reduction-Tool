from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .calibration import create_master_bias, create_master_flat, reduce_image
from .io import scan_project
from .models import ProjectPaths


ALIGNMENT_NONE = "none"
ALIGNMENT_AUTOMATIC = "automatic"
ALIGNMENT_MANUAL = "manual"
ALIGNMENT_MODES = (ALIGNMENT_NONE, ALIGNMENT_AUTOMATIC, ALIGNMENT_MANUAL)
BACKGROUND_OFF = "off"
BACKGROUND_MEDIAN_GRID = "median_grid"
BACKGROUND_POLYNOMIAL = "polynomial"
BACKGROUND_HYBRID = "hybrid"
BACKGROUND_CORRECTION_MODES = (
    BACKGROUND_OFF,
    BACKGROUND_MEDIAN_GRID,
    BACKGROUND_POLYNOMIAL,
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
    background_stats: dict[str, object] = field(default_factory=dict)


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


def _sigma_clip_values(values: np.ndarray, sigma: float) -> np.ndarray:
    data = values[np.isfinite(values)]
    if data.size == 0:
        return data
    center, spread = _robust_sigma(data)
    return data[np.abs(data - center) <= max(0.5, float(sigma)) * spread]


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


def normalise_preview(image: np.ndarray, low: float = 0.3, high: float = 99.7) -> np.ndarray:
    data = _safe_float_image(image)
    if data.ndim == 2:
        lo, hi = np.percentile(data, [low, high])
        if hi <= lo:
            hi = lo + 1.0
        return np.clip((data - lo) / (hi - lo), 0, 1)
    output = np.zeros_like(data, dtype=np.float32)
    for channel in range(data.shape[2]):
        plane = data[..., channel]
        lo, hi = np.percentile(plane, [low, high])
        if hi <= lo:
            hi = lo + 1.0
        output[..., channel] = np.clip((plane - lo) / (hi - lo), 0, 1)
    return output


def build_star_mask(
    image: np.ndarray,
    sigma_threshold: float = 5.0,
    dilation_px: int = 2,
    highpass_sigma: float = 20.0,
) -> np.ndarray:
    data = _safe_float_image(image)
    try:
        from scipy.ndimage import gaussian_filter, label, maximum_filter

        smooth = gaussian_filter(data, sigma=max(3.0, float(highpass_sigma)), mode="nearest")
        residual = data - smooth
        median, sigma = _robust_sigma(residual)
        threshold = median + max(0.5, float(sigma_threshold)) * sigma
        candidates = residual > threshold
        candidates &= residual >= maximum_filter(residual, size=3, mode="nearest") * 0.35
        labeled, count = label(candidates)
        if count:
            max_component_area = max(16, int(data.size * 0.0025))
            cleaned = np.zeros_like(candidates, dtype=bool)
            for component in range(1, count + 1):
                component_mask = labeled == component
                area = int(np.count_nonzero(component_mask))
                if 1 <= area <= max_component_area:
                    cleaned |= component_mask
            candidates = cleaned
    except Exception:
        smooth = data - np.median(data)
        median, sigma = _robust_sigma(smooth)
        candidates = smooth > median + max(0.5, float(sigma_threshold)) * sigma
    return _dilate_mask(candidates, int(dilation_px))


def build_elliptical_object_mask(
    shape: tuple[int, int],
    center: tuple[float, float],
    axes: tuple[float, float],
    angle: float = 0.0,
    feather_px: int = 0,
) -> np.ndarray:
    height, width = int(shape[0]), int(shape[1])
    center_x, center_y = center
    axis_a = max(1.0, float(axes[0]) + max(0, int(feather_px)))
    axis_b = max(1.0, float(axes[1]) + max(0, int(feather_px)))
    theta = np.deg2rad(float(angle))
    y, x = np.ogrid[:height, :width]
    dx = x - center_x
    dy = y - center_y
    rotated_x = dx * np.cos(theta) + dy * np.sin(theta)
    rotated_y = -dx * np.sin(theta) + dy * np.cos(theta)
    return ((rotated_x / axis_a) ** 2 + (rotated_y / axis_b) ** 2) <= 1.0


def auto_object_mask_geometry(image: np.ndarray, search_region_fraction: float = 0.45) -> dict[str, object]:
    data = _safe_float_image(image)
    height, width = data.shape
    fallback = {
        "center": (width / 2.0, height / 2.0),
        "axes": (width * 0.10, height * 0.22),
        "angle": 0.0,
        "source": "fallback_center",
    }
    fraction = min(0.9, max(0.2, float(search_region_fraction)))
    half_w = int(width * fraction / 2.0)
    half_h = int(height * fraction / 2.0)
    cx = width // 2
    cy = height // 2
    x0, x1 = max(0, cx - half_w), min(width, cx + half_w)
    y0, y1 = max(0, cy - half_h), min(height, cy + half_h)
    if x1 <= x0 or y1 <= y0:
        return fallback
    region = data[y0:y1, x0:x1]
    try:
        from scipy.ndimage import gaussian_filter, label, center_of_mass

        smooth = gaussian_filter(region, sigma=max(6.0, min(height, width) / 45.0), mode="nearest")
        median, sigma = _robust_sigma(smooth)
        threshold = median + 1.5 * sigma
        candidate = smooth > threshold
        labeled, count = label(candidate)
        best_label = 0
        best_score = 0.0
        for component in range(1, count + 1):
            component_mask = labeled == component
            area = int(np.count_nonzero(component_mask))
            if area < max(20, region.size * 0.002) or area > region.size * 0.75:
                continue
            score = float(np.sum(smooth[component_mask])) * np.sqrt(area)
            if score > best_score:
                best_score = score
                best_label = component
        if best_label:
            component_mask = labeled == best_label
            local_y, local_x = center_of_mass(smooth, labels=component_mask, index=True)
            center = (float(x0 + local_x), float(y0 + local_y))
            edge_margin_x = width * (1.0 - fraction) / 2.0
            edge_margin_y = height * (1.0 - fraction) / 2.0
            if edge_margin_x <= center[0] <= width - edge_margin_x and edge_margin_y <= center[1] <= height - edge_margin_y:
                return {
                    "center": center,
                    "axes": (width * 0.10, height * 0.22),
                    "angle": 0.0,
                    "source": "auto_central_region",
                }
    except Exception:
        pass
    return fallback


def auto_object_mask(image: np.ndarray, axes_scale: tuple[float, float] = (0.10, 0.22)) -> tuple[np.ndarray, dict[str, object]]:
    geometry = auto_object_mask_geometry(image)
    center = geometry["center"]
    axes = geometry.get("axes", (image.shape[1] * axes_scale[0], image.shape[0] * axes_scale[1]))
    angle = float(geometry.get("angle", 0.0))
    mask = build_elliptical_object_mask(image.shape, center, axes, angle)
    return mask, geometry
def _sky_stats(image: np.ndarray, sky_mask: np.ndarray) -> dict[str, float | list[float]]:
    values = np.asarray(image, dtype=float)[sky_mask]
    if values.size == 0:
        values = np.asarray(image, dtype=float).reshape(-1)
    return {
        "median": float(np.median(values)),
        "std": float(np.std(values)),
        "percentiles": [float(v) for v in np.percentile(values, [1, 50, 99])],
    }



def _edge_center_masks(shape: tuple[int, int], protected_mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    height, width = shape
    y, x = np.ogrid[:height, :width]
    margin_y = max(1, int(height * 0.12))
    margin_x = max(1, int(width * 0.12))
    edge = (x < margin_x) | (x >= width - margin_x) | (y < margin_y) | (y >= height - margin_y)
    center_radius_x = width * 0.22
    center_radius_y = height * 0.22
    center = ((x - width / 2.0) / center_radius_x) ** 2 + ((y - height / 2.0) / center_radius_y) ** 2 <= 1.0
    if protected_mask is not None:
        usable = ~np.asarray(protected_mask, dtype=bool)
        edge &= usable
        center &= usable
    return edge, center


def _gradient_metrics(before: np.ndarray, after: np.ndarray, protected_mask: np.ndarray) -> dict[str, float]:
    edge_mask, center_mask = _edge_center_masks(before.shape, protected_mask)
    if not np.any(edge_mask) or not np.any(center_mask):
        return {
            "median_edge_before": 0.0,
            "median_center_before": 0.0,
            "median_edge_after": 0.0,
            "median_center_after": 0.0,
            "edge_center_delta_before": 0.0,
            "edge_center_delta_after": 0.0,
            "gradient_reduction_percent": 0.0,
        }
    edge_before = float(np.median(before[edge_mask]))
    center_before = float(np.median(before[center_mask]))
    edge_after = float(np.median(after[edge_mask]))
    center_after = float(np.median(after[center_mask]))
    delta_before = edge_before - center_before
    delta_after = edge_after - center_after
    reduction = 0.0
    if abs(delta_before) > 1e-12:
        reduction = (1.0 - abs(delta_after) / abs(delta_before)) * 100.0
    return {
        "median_edge_before": edge_before,
        "median_center_before": center_before,
        "median_edge_after": edge_after,
        "median_center_after": center_after,
        "edge_center_delta_before": delta_before,
        "edge_center_delta_after": delta_after,
        "gradient_reduction_percent": reduction,
    }

def _median_grid_background(
    image: np.ndarray,
    sky_mask: np.ndarray,
    grid_size: int,
    smoothing_sigma: float,
    sigma_clip: bool,
    sigma_clip_sigma: float,
) -> np.ndarray:
    from scipy.ndimage import gaussian_filter, zoom

    data = _safe_float_image(image)
    height, width = data.shape
    grid = max(16, int(grid_size))
    samples_y = max(4, int(np.ceil(height / grid)))
    samples_x = max(4, int(np.ceil(width / grid)))
    low = np.empty((samples_y, samples_x), dtype=np.float32)
    global_values = data[sky_mask]
    if sigma_clip:
        global_values = _sigma_clip_values(global_values, sigma_clip_sigma)
    global_median = float(np.median(global_values)) if global_values.size else float(np.median(data))

    for row in range(samples_y):
        y0 = int(row * height / samples_y)
        y1 = int((row + 1) * height / samples_y)
        for col in range(samples_x):
            x0 = int(col * width / samples_x)
            x1 = int((col + 1) * width / samples_x)
            block = data[y0:y1, x0:x1]
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
    image: np.ndarray,
    sky_mask: np.ndarray,
    order: int,
    sigma_clip: bool,
    sigma_clip_sigma: float,
) -> np.ndarray:
    data = _safe_float_image(image)
    height, width = data.shape
    y, x = np.indices(data.shape, dtype=np.float32)
    xn = (x / max(1, width - 1)) * 2.0 - 1.0
    yn = (y / max(1, height - 1)) * 2.0 - 1.0
    values = data[sky_mask]
    sample_x = xn[sky_mask]
    sample_y = yn[sky_mask]
    if sigma_clip and values.size:
        center, spread = _robust_sigma(values)
        keep = np.abs(values - center) <= max(0.5, float(sigma_clip_sigma)) * spread
        values = values[keep]
        sample_x = sample_x[keep]
        sample_y = sample_y[keep]
    if values.size < 16:
        return np.full_like(data, float(np.median(data)), dtype=np.float32)
    terms = []
    full_terms = []
    max_order = max(0, min(4, int(order)))
    for i in range(max_order + 1):
        for j in range(max_order + 1 - i):
            terms.append((sample_x ** i) * (sample_y ** j))
            full_terms.append((xn ** i) * (yn ** j))
    design = np.vstack(terms).T
    coeffs, *_ = np.linalg.lstsq(design, values, rcond=None)
    background = np.zeros_like(data, dtype=np.float32)
    for coeff, term in zip(coeffs, full_terms):
        background += float(coeff) * term.astype(np.float32)
    return background


def _photutils_background(image: np.ndarray, protected_mask: np.ndarray, grid_size: int, sigma_clip_sigma: float) -> np.ndarray:
    from astropy.stats import SigmaClip
    from photutils.background import Background2D, MedianBackground

    box = max(16, int(grid_size))
    sigma_clipper = SigmaClip(sigma=max(0.5, float(sigma_clip_sigma)))
    background = Background2D(
        image,
        box_size=(box, box),
        filter_size=(3, 3),
        mask=protected_mask,
        sigma_clip=sigma_clipper,
        bkg_estimator=MedianBackground(),
    )
    return np.asarray(background.background, dtype=np.float32)


def _estimate_band_background(
    image: np.ndarray,
    protected_mask: np.ndarray,
    method: str,
    grid_size: int,
    smoothing_sigma: float,
    polynomial_order: int,
    sigma_clip: bool,
    sigma_clip_sigma: float,
) -> tuple[np.ndarray, str]:
    sky_mask = ~protected_mask
    if method == BACKGROUND_POLYNOMIAL:
        return _polynomial_background(image, sky_mask, polynomial_order, sigma_clip, sigma_clip_sigma), BACKGROUND_POLYNOMIAL
    if method == BACKGROUND_HYBRID:
        try:
            return _photutils_background(image, protected_mask, grid_size, sigma_clip_sigma), "hybrid_photutils"
        except Exception:
            grid_model = _median_grid_background(image, sky_mask, grid_size, smoothing_sigma, sigma_clip, sigma_clip_sigma)
            poly_model = _polynomial_background(image, sky_mask, polynomial_order, sigma_clip, sigma_clip_sigma)
            return (0.8 * grid_model + 0.2 * poly_model).astype(np.float32), BACKGROUND_HYBRID
    return _median_grid_background(image, sky_mask, grid_size, smoothing_sigma, sigma_clip, sigma_clip_sigma), BACKGROUND_MEDIAN_GRID


def remove_band_background(
    image,
    method="hybrid",
    star_sigma_threshold=5.0,
    star_mask_dilation_px=2,
    object_mask=None,
    grid_size=128,
    smoothing_sigma=5.0,
    polynomial_order=2,
    sigma_clip=True,
    sigma_clip_sigma=3.0,
    correction_strength=1.0,
    preserve_sky_median=True,
    debug=False,
):
    data = _safe_float_image(image)
    method = BACKGROUND_HYBRID if method == "hybrid" else str(method)
    if method == BACKGROUND_OFF:
        empty_mask = np.zeros(data.shape, dtype=bool)
        return {
            "corrected": data.copy(),
            "background_model": np.full_like(data, float(np.median(data)), dtype=np.float32),
            "mask": empty_mask,
            "sky_mask": ~empty_mask,
            "stats": {
                "method": BACKGROUND_OFF,
                "sky_pixels_used_percent": 100.0,
                "before": _sky_stats(data, ~empty_mask),
                "after": _sky_stats(data, ~empty_mask),
            },
            "debug_images": {},
        }

    star_mask = build_star_mask(data, star_sigma_threshold, star_mask_dilation_px)
    protected_mask = star_mask.copy()
    if object_mask is not None:
        protected_mask |= np.asarray(object_mask, dtype=bool)
    sky_mask = ~protected_mask
    if np.count_nonzero(sky_mask) < data.size * 0.05:
        protected_mask = star_mask
        sky_mask = ~protected_mask

    before_stats = _sky_stats(data, sky_mask)
    background_model, used_method = _estimate_band_background(
        data,
        protected_mask,
        method,
        grid_size,
        smoothing_sigma,
        polynomial_order,
        bool(sigma_clip),
        sigma_clip_sigma,
    )
    sky_level = float(np.median(background_model[sky_mask])) if np.any(sky_mask) else float(np.median(background_model))
    strength = min(1.2, max(0.0, float(correction_strength)))
    correction_anchor = sky_level if preserve_sky_median else 0.0
    corrected = data - strength * (background_model - correction_anchor)
    after_stats = _sky_stats(corrected, sky_mask)
    gradient = _gradient_metrics(data, corrected, protected_mask)
    stats = {
        "method": used_method,
        "sky_level": sky_level,
        "sky_pixels_used_percent": float(np.count_nonzero(sky_mask) * 100.0 / sky_mask.size),
        "before": before_stats,
        "after": after_stats,
        "star_pixels": int(np.count_nonzero(star_mask)),
        "object_pixels": int(np.count_nonzero(object_mask)) if object_mask is not None else 0,
        "gradient_metrics": gradient,
        "parameters": {
            "star_sigma_threshold": float(star_sigma_threshold),
            "star_mask_dilation_px": int(star_mask_dilation_px),
            "grid_size": int(grid_size),
            "smoothing_sigma": float(smoothing_sigma),
            "polynomial_order": int(polynomial_order),
            "sigma_clip": bool(sigma_clip),
            "sigma_clip_sigma": float(sigma_clip_sigma),
            "correction_strength": strength,
            "preserve_sky_median": bool(preserve_sky_median),
        },
    }
    debug_images = {}
    if debug:
        debug_images = {
            "original": normalise_preview(data),
            "mask": protected_mask.astype(np.float32),
            "background_model": normalise_preview(background_model),
            "corrected": normalise_preview(corrected),
        }
    return {
        "corrected": corrected.astype(np.float32),
        "background_model": background_model.astype(np.float32),
        "mask": protected_mask,
        "sky_mask": sky_mask,
        "stats": stats,
        "debug_images": debug_images,
    }


def apply_background_correction(stacked: dict[str, np.ndarray], background_correction: str, **kwargs) -> dict[str, np.ndarray]:
    if background_correction == BACKGROUND_OFF:
        return stacked
    return {
        band: remove_band_background(image, method=background_correction, **kwargs)["corrected"]
        for band, image in stacked.items()
    }


def compose_linear_rgb(stacked_bands: dict[str, np.ndarray], channel_mapping: dict[str, str] | None = None) -> np.ndarray:
    if not stacked_bands:
        raise ValueError("No stacked object images are available.")
    mapping = channel_mapping or {"R": "R", "G": "V", "B": "B"}
    fallback = next(iter(stacked_bands.values()))
    channels = []
    for rgb_channel in ("R", "G", "B"):
        band = mapping.get(rgb_channel, rgb_channel)
        channels.append(np.asarray(stacked_bands.get(band, np.zeros_like(fallback)), dtype=np.float32))
    return np.dstack(channels).astype(np.float32)


def neutralize_rgb_background(rgb: np.ndarray, sky_mask: np.ndarray, strength: float = 1.0) -> tuple[np.ndarray, dict[str, object]]:
    data = _safe_float_image(rgb)
    mask = np.asarray(sky_mask, dtype=bool)
    if mask.shape != data.shape[:2] or not np.any(mask):
        mask = np.ones(data.shape[:2], dtype=bool)
    medians = np.array([float(np.median(data[..., channel][mask])) for channel in range(3)], dtype=np.float32)
    target = float(np.median(medians))
    amount = min(1.0, max(0.0, float(strength)))
    neutralized = data - amount * (medians - target).reshape(1, 1, 3)
    after = np.array([float(np.median(neutralized[..., channel][mask])) for channel in range(3)], dtype=np.float32)
    stats = {
        "background_median_before": medians.tolist(),
        "background_median_after": after.tolist(),
        "neutral_target": target,
        "strength": amount,
    }
    return neutralized.astype(np.float32), stats


def final_stretch_rgb(
    rgb: np.ndarray,
    sky_mask: np.ndarray | None = None,
    target_background_level: float = 0.04,
    black_point_percentile: float = 0.5,
    white_point_percentile: float = 99.7,
    stretch_strength: float = 8.0,
) -> tuple[np.ndarray, dict[str, object]]:
    data = _safe_float_image(rgb)
    if data.ndim != 3 or data.shape[2] != 3:
        raise ValueError("rgb must be an RGB array with shape (height, width, 3).")
    if sky_mask is None or np.asarray(sky_mask).shape != data.shape[:2] or not np.any(sky_mask):
        mask = np.ones(data.shape[:2], dtype=bool)
    else:
        mask = np.asarray(sky_mask, dtype=bool)

    sky_median_before = np.array([float(np.median(data[..., channel][mask])) for channel in range(3)], dtype=np.float32)
    black_point = np.array([
        float(np.percentile(data[..., channel][mask], black_point_percentile))
        for channel in range(3)
    ], dtype=np.float32)
    shifted = data - black_point.reshape(1, 1, 3)
    clipped_low = int(np.count_nonzero(shifted < 0))
    shifted = np.clip(shifted, 0, None)
    white_point = np.array([
        float(np.percentile(shifted[..., channel], white_point_percentile))
        for channel in range(3)
    ], dtype=np.float32)
    scale = float(np.max(white_point))
    if scale <= 0:
        scale = float(np.percentile(shifted, white_point_percentile))
    scale = max(scale, 1e-6)
    normalized = shifted / scale
    strength = max(0.1, float(stretch_strength))
    stretched = np.arcsinh(strength * normalized) / np.arcsinh(strength)

    sky_median = np.array([float(np.median(stretched[..., channel][mask])) for channel in range(3)], dtype=np.float32)
    current_background = float(np.median(sky_median))
    target = min(0.2, max(0.0, float(target_background_level)))
    if current_background > 1e-6:
        stretched *= target / current_background
    clipped_high = int(np.count_nonzero(stretched > 1.0))
    stretched = np.clip(stretched, 0, 1)
    sky_median_after = np.array([float(np.median(stretched[..., channel][mask])) for channel in range(3)], dtype=np.float32)
    before_luminance = np.median(data, axis=2)[mask]
    after_luminance = np.median(stretched, axis=2)[mask]
    hist_before, hist_before_edges = np.histogram(before_luminance, bins=64)
    hist_after, hist_after_edges = np.histogram(after_luminance, bins=64, range=(0.0, 1.0))
    stats = {
        "sky_median_before_stretch": sky_median_before.tolist(),
        "sky_median_after_stretch": sky_median_after.tolist(),
        "target_background_level": target,
        "black_point": black_point.tolist(),
        "white_point": white_point.tolist(),
        "clipped_low_percent": float(clipped_low * 100.0 / max(1, shifted.size)),
        "clipped_high_percent": float(clipped_high * 100.0 / max(1, stretched.size)),
        "stretch_strength": strength,
        "black_point_percentile": float(black_point_percentile),
        "white_point_percentile": float(white_point_percentile),
        "histogram_before_stretch": {
            "counts": hist_before.astype(int).tolist(),
            "bin_edges": hist_before_edges.astype(float).tolist(),
        },
        "histogram_after_stretch": {
            "counts": hist_after.astype(int).tolist(),
            "bin_edges": hist_after_edges.astype(float).tolist(),
        },
    }
    return np.uint8(np.clip(stretched, 0, 1) * 255), stats


def stretch_rgb(rgb: np.ndarray, method: str = "final", stretch: float = 5, q: float = 8) -> tuple[np.ndarray, dict[str, object]]:
    return final_stretch_rgb(rgb, target_background_level=0.04, stretch_strength=max(0.1, float(q)))
def create_available_channel_rgb(stacked: dict[str, np.ndarray], stretch: float, q_value: float) -> np.ndarray:
    linear_rgb = compose_linear_rgb(stacked)
    stretched, _stats = final_stretch_rgb(linear_rgb, stretch_strength=q_value)
    return stretched
def run_reduction(
    paths: ProjectPaths,
    object_name: str = "object",
    stretch: float = 5,
    q_value: float = 8,
    alignment_mode: str = ALIGNMENT_AUTOMATIC,
    progress_callback: ProgressCallback | None = None,
    object_file_selection: dict[str, list[Path]] | None = None,
    background_correction: str = BACKGROUND_OFF,
    background_grid_size: int = 128,
    background_smoothing_sigma: float = 5.0,
    background_polynomial_order: int = 2,
    background_sigma_clip: bool = True,
    background_sigma_clip_sigma: float = 3.0,
    background_correction_strength: float = 1.0,
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

    background_stats: dict[str, object] = {}
    sky_masks = []
    if background_correction != BACKGROUND_OFF:
        report(88, "Removing band background gradients")
        mask_rgb = compose_linear_rgb(stacked)
        mask_luminance = np.median(mask_rgb, axis=2)
        object_geometry = auto_object_mask_geometry(mask_luminance)
        object_mask = build_elliptical_object_mask(
            mask_luminance.shape,
            object_geometry["center"],
            object_geometry["axes"],
            float(object_geometry.get("angle", 0.0)),
        )
        background_stats["object_mask"] = object_geometry
        corrected_stacked = {}
        band_stats = {}
        for band, image in stacked.items():
            result = remove_band_background(
                image,
                method=background_correction,
                object_mask=object_mask,
                grid_size=background_grid_size,
                smoothing_sigma=background_smoothing_sigma,
                polynomial_order=background_polynomial_order,
                sigma_clip=background_sigma_clip,
                sigma_clip_sigma=background_sigma_clip_sigma,
                correction_strength=background_correction_strength,
                debug=False,
            )
            corrected_stacked[band] = result["corrected"]
            band_stats[band] = result["stats"]
            sky_masks.append(result["sky_mask"])
        stacked = corrected_stacked
        background_stats["bands"] = band_stats

    report(90, "Composing linear RGB image")
    linear_rgb = compose_linear_rgb(stacked)
    if sky_masks:
        sky_mask = np.logical_and.reduce(sky_masks)
        linear_rgb, neutralization_stats = neutralize_rgb_background(linear_rgb, sky_mask, strength=1.0)
        background_stats["rgb_neutralization"] = neutralization_stats
    if sky_masks:
        stretch_mask = np.logical_and.reduce(sky_masks)
    else:
        stretch_mask = np.ones(linear_rgb.shape[:2], dtype=bool)
    rgb, stretch_stats = final_stretch_rgb(linear_rgb, sky_mask=stretch_mask, stretch_strength=q_value)
    background_stats["stretch"] = stretch_stats
    if "bands" in background_stats:
        background_stats["gradient_metrics"] = {
            band: stats.get("gradient_metrics", {})
            for band, stats in background_stats["bands"].items()
        }
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
        background_stats=background_stats,
    )
