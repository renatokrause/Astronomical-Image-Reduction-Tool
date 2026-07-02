from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import numpy as np

from PySide6.QtGui import QImage

from airt.core.bands import normalize_band_name, sort_bands_recommended


@dataclass
class FinalRenderResult:
    image: np.ndarray
    bands: list[str]
    mode: str
    masters: dict[str, np.ndarray]


def selected_object_files_by_band(project) -> dict[str, list[str]]:
    if not project:
        return {}

    return {
        band: list(paths)
        for band, paths in getattr(project, "selected_object_files", {}).items()
        if band and band != "-" and paths
    }


def selected_calibration_files(project) -> dict[str, list[str]]:
    if not project:
        return {}

    selected = getattr(project, "selected_calibration_files", None)

    if isinstance(selected, dict):
        return {
            str(key): list(paths)
            for key, paths in selected.items()
            if paths
        }

    return {}


def load_fits_array(path: Path) -> np.ndarray:
    from astropy.io import fits

    data = fits.getdata(path, 0)
    data = np.asarray(data)

    if data.ndim > 2:
        data = np.squeeze(data)

        if data.ndim > 2:
            data = data[0]

    if data.ndim != 2:
        raise ValueError(f"Unsupported FITS dimensions for {path.name}: {data.shape}")

    data = data.astype(np.float32, copy=False)
    data[~np.isfinite(data)] = np.nan

    return data


def robust_median_stack(arrays: list[np.ndarray]) -> np.ndarray:
    if not arrays:
        raise RuntimeError("No arrays to stack.")

    reference_shape = arrays[0].shape
    arrays = [array for array in arrays if array.shape == reference_shape]

    if not arrays:
        raise RuntimeError("No compatible arrays to stack.")

    if len(arrays) == 1:
        return arrays[0].astype(np.float32, copy=True)

    with np.errstate(all="ignore"):
        stacked = np.nanmedian(np.stack(arrays, axis=0), axis=0)

    return stacked.astype(np.float32, copy=False)


def safe_percentile(data: np.ndarray, percentile: float, default: float = 0.0) -> float:
    finite = np.isfinite(data)

    if not np.any(finite):
        return default

    return float(np.percentile(data[finite], percentile))


def normalize_master(data: np.ndarray) -> np.ndarray:
    data = data.astype(np.float32, copy=False)
    finite = np.isfinite(data)

    if not np.any(finite):
        return np.zeros_like(data, dtype=np.float32)

    low = safe_percentile(data, 1.0)
    high = safe_percentile(data, 99.8)

    if high <= low:
        low = float(np.nanmin(data))
        high = float(np.nanmax(data))

    if high <= low:
        high = low + 1.0

    out = (data - low) / (high - low)
    out = np.clip(out, 0, 1)
    out[~finite] = 0

    return out.astype(np.float32, copy=False)


def calibration_paths_for_kind(calibration: dict[str, list[str]], kind: str, band: str | None = None) -> list[Path]:
    kind = kind.upper()
    band_norm = normalize_band_name(band) if band else ""
    result: list[Path] = []

    for key, paths in calibration.items():
        key_text = str(key).upper()
        key_norm = normalize_band_name(key)

        matches_kind = kind in key_text or key_text == kind

        if kind == "FLAT" and not matches_kind:
            matches_kind = "FLAT" in key_text or "FLATS" in key_text

        if not matches_kind:
            continue

        if kind == "FLAT" and band_norm:
            # If the flat key carries a band, prefer matching flats.
            possible_band = key_text.replace("FLAT", "").replace("FLATS", "")
            possible_band = possible_band.replace(":", " ").replace("|", " ").replace("/", " ").strip()

            if possible_band:
                tokens = [token for token in re.split(r"\s+", possible_band) if token]
                normalized_tokens = {normalize_band_name(token) for token in tokens}

                if normalized_tokens and band_norm not in normalized_tokens:
                    continue

        for path_text in paths:
            path = Path(path_text)

            if path.exists():
                result.append(path)

    return result


def build_master_bias(calibration: dict[str, list[str]]) -> np.ndarray | None:
    paths = calibration_paths_for_kind(calibration, "BIAS")

    if not paths:
        return None

    arrays = []

    for path in paths:
        try:
            arrays.append(load_fits_array(path))
        except Exception:
            continue

    if not arrays:
        return None

    return robust_median_stack(arrays)


def build_master_dark(calibration: dict[str, list[str]], master_bias: np.ndarray | None) -> np.ndarray | None:
    paths = calibration_paths_for_kind(calibration, "DARK")

    if not paths:
        return None

    arrays = []

    for path in paths:
        try:
            data = load_fits_array(path)

            if master_bias is not None and master_bias.shape == data.shape:
                data = data - master_bias

            arrays.append(data)
        except Exception:
            continue

    if not arrays:
        return None

    return robust_median_stack(arrays)


def build_master_flat(
    calibration: dict[str, list[str]],
    band: str,
    master_bias: np.ndarray | None,
    master_dark: np.ndarray | None,
) -> np.ndarray | None:
    paths = calibration_paths_for_kind(calibration, "FLAT", band)

    if not paths:
        # Fallback: use all flats when there are no band-specific flat keys.
        all_flat_paths = []

        for key, paths_text in calibration.items():
            if "FLAT" in str(key).upper():
                all_flat_paths.extend(Path(path_text) for path_text in paths_text if Path(path_text).exists())

        paths = all_flat_paths

    if not paths:
        return None

    arrays = []

    for path in paths:
        try:
            data = load_fits_array(path)

            if master_bias is not None and master_bias.shape == data.shape:
                data = data - master_bias

            if master_dark is not None and master_dark.shape == data.shape:
                data = data - master_dark

            arrays.append(data)
        except Exception:
            continue

    if not arrays:
        return None

    flat = robust_median_stack(arrays)
    median = float(np.nanmedian(flat))

    if not np.isfinite(median) or abs(median) < 1e-8:
        return None

    flat = flat / median
    flat = np.where(np.isfinite(flat) & (np.abs(flat) > 1e-6), flat, 1.0)

    return flat.astype(np.float32, copy=False)


def calibrate_light(
    data: np.ndarray,
    master_bias: np.ndarray | None,
    master_dark: np.ndarray | None,
    master_flat: np.ndarray | None,
) -> np.ndarray:
    calibrated = data.astype(np.float32, copy=True)

    if master_bias is not None and master_bias.shape == calibrated.shape:
        calibrated = calibrated - master_bias

    if master_dark is not None and master_dark.shape == calibrated.shape:
        calibrated = calibrated - master_dark

    if master_flat is not None and master_flat.shape == calibrated.shape:
        calibrated = calibrated / master_flat

    calibrated[~np.isfinite(calibrated)] = np.nan

    return calibrated.astype(np.float32, copy=False)


def estimate_integer_shift(reference: np.ndarray, moving: np.ndarray) -> tuple[float, float]:
    reference = np.nan_to_num(reference, nan=0.0)
    moving = np.nan_to_num(moving, nan=0.0)

    reference = reference - np.median(reference)
    moving = moving - np.median(moving)

    try:
        from skimage.registration import phase_cross_correlation

        shift_yx, _, _ = phase_cross_correlation(reference, moving, upsample_factor=10)
        return float(shift_yx[1]), float(shift_yx[0])
    except Exception:
        pass

    try:
        f_reference = np.fft.fftn(reference)
        f_moving = np.fft.fftn(moving)
        product = f_reference * f_moving.conj()
        product /= np.maximum(np.abs(product), 1e-8)

        correlation = np.fft.ifftn(product)
        maxima = np.unravel_index(np.argmax(np.abs(correlation)), correlation.shape)
        shifts = np.array(maxima, dtype=np.float32)

        for index, dimension in enumerate(reference.shape):
            if shifts[index] > dimension // 2:
                shifts[index] -= dimension

        return float(-shifts[1]), float(-shifts[0])
    except Exception:
        return 0.0, 0.0


def shifted_array(image: np.ndarray, x: float, y: float, fill: float = np.nan) -> np.ndarray:
    try:
        from scipy.ndimage import shift

        return shift(
            image,
            shift=(y, x),
            order=1,
            mode="constant",
            cval=fill,
            prefilter=False,
        ).astype(np.float32, copy=False)
    except Exception:
        shifted = np.roll(image, shift=(int(round(y)), int(round(x))), axis=(0, 1))

        if fill is not np.nan:
            return shifted.astype(np.float32, copy=False)

        # Mask wrapped regions when falling back to roll.
        if int(round(y)) > 0:
            shifted[: int(round(y)), :] = np.nan
        elif int(round(y)) < 0:
            shifted[int(round(y)) :, :] = np.nan

        if int(round(x)) > 0:
            shifted[:, : int(round(x))] = np.nan
        elif int(round(x)) < 0:
            shifted[:, int(round(x)) :] = np.nan

        return shifted.astype(np.float32, copy=False)


def stack_band_frames(
    paths: list[str],
    master_bias: np.ndarray | None,
    master_dark: np.ndarray | None,
    master_flat: np.ndarray | None,
) -> np.ndarray:
    calibrated = []

    for path_text in paths:
        path = Path(path_text)

        if not path.exists():
            continue

        try:
            data = load_fits_array(path)
            calibrated.append(calibrate_light(data, master_bias, master_dark, master_flat))
        except Exception:
            continue

    if not calibrated:
        raise RuntimeError("No valid light frames for band.")

    reference = calibrated[0]
    aligned = [reference]

    for data in calibrated[1:]:
        if data.shape != reference.shape:
            continue

        x, y = estimate_integer_shift(reference, data)
        aligned.append(shifted_array(data, x, y))

    return robust_median_stack(aligned)


def estimate_background(image: np.ndarray, block_size: int = 128, protection: str = "medium") -> np.ndarray:
    height, width = image.shape
    block_size = max(16, int(block_size))

    pad_h = (block_size - height % block_size) % block_size
    pad_w = (block_size - width % block_size) % block_size

    padded = np.pad(image, ((0, pad_h), (0, pad_w)), mode="edge")

    if protection == "low":
        percentile = 90.0
    elif protection == "high":
        percentile = 70.0
    else:
        percentile = 80.0

    threshold = np.nanpercentile(padded, percentile)
    protected = np.where(padded <= threshold, padded, np.nan)

    h2, w2 = padded.shape
    blocks = protected.reshape(h2 // block_size, block_size, w2 // block_size, block_size)

    with np.errstate(all="ignore"):
        coarse = np.nanmedian(blocks, axis=(1, 3))

    if np.isnan(coarse).any():
        fallback = float(np.nanmedian(protected))

        if not np.isfinite(fallback):
            fallback = float(np.nanmedian(padded))

        coarse = np.where(np.isfinite(coarse), coarse, fallback)

    background = np.repeat(np.repeat(coarse, block_size, axis=0), block_size, axis=1)
    background = background[:height, :width]

    try:
        from scipy.ndimage import gaussian_filter

        background = gaussian_filter(background, sigma=max(2.0, block_size / 2.5))
    except Exception:
        pass

    return background.astype(np.float32, copy=False)


def correct_background_linear(image: np.ndarray, settings: dict) -> np.ndarray:
    if not settings or not settings.get("enabled", False):
        return image.astype(np.float32, copy=False)

    strength = float(settings.get("strength", 0.35))
    scale = int(settings.get("scale", 128))
    protection = settings.get("object_protection", "medium")

    background = estimate_background(image, scale, protection)
    variation = background - float(np.nanmedian(background))
    corrected = image - strength * variation
    corrected[~np.isfinite(corrected)] = np.nan

    return corrected.astype(np.float32, copy=False)


def linear_to_unit(image: np.ndarray, black_percentile: float = 0.5, white_percentile: float = 99.8) -> np.ndarray:
    finite = np.isfinite(image)

    if not np.any(finite):
        return np.zeros_like(image, dtype=np.float32)

    black = float(np.percentile(image[finite], black_percentile))
    white = float(np.percentile(image[finite], white_percentile))

    if white <= black:
        black = float(np.percentile(image[finite], 1.0))
        white = float(np.percentile(image[finite], 99.5))

    if white <= black:
        white = black + 1.0

    out = (image - black) / (white - black)
    out = np.clip(out, 0, 1)
    out[~finite] = 0

    return out.astype(np.float32, copy=False)


def asinh_stretch(unit: np.ndarray, stretch: str) -> np.ndarray:
    if stretch == "linear":
        factor = 1.0
        gamma = 1.0
    elif stretch == "soft":
        factor = 6.0
        gamma = 0.90
    elif stretch == "strong":
        factor = 18.0
        gamma = 0.72
    else:
        factor = 10.0
        gamma = 0.82

    unit = np.clip(unit, 0, 1)

    if factor > 1.0:
        out = np.arcsinh(unit * factor) / np.arcsinh(factor)
    else:
        out = unit

    if gamma != 1.0:
        out = np.power(np.clip(out, 0, 1), gamma)

    return np.clip(out, 0, 1).astype(np.float32, copy=False)


def final_stretch_channel(image: np.ndarray, stretch: str) -> np.ndarray:
    unit = linear_to_unit(image, 0.5, 99.85)
    return asinh_stretch(unit, stretch)


def channel_for_band(band: str, color_mapping: dict) -> str:
    direct = color_mapping.get(band, {})

    if direct.get("channel"):
        return str(direct["channel"]).upper().strip()

    normalized = normalize_band_name(band)

    for saved_band, item in color_mapping.items():
        if normalize_band_name(saved_band) == normalized and item.get("channel"):
            return str(item["channel"]).upper().strip()

    if normalized == "L":
        return "L"

    if normalized in {"R", "HA", "SII", "I"}:
        return "R"

    if normalized in {"G", "V"}:
        return "G"

    if normalized in {"B", "HB", "OIII"}:
        return "B"

    return "-"


def channel_weights(channel: str) -> tuple[float, float, float]:
    channel = (channel or "-").upper().strip()

    if channel == "R":
        return (1.0, 0.0, 0.0)

    if channel == "G":
        return (0.0, 1.0, 0.0)

    if channel == "B":
        return (0.0, 0.0, 1.0)

    if channel == "R+G":
        return (1.0, 1.0, 0.0)

    if channel == "R+B":
        return (1.0, 0.0, 1.0)

    if channel == "G+B":
        return (0.0, 1.0, 1.0)

    if channel == "R+G+B":
        return (1.0, 1.0, 1.0)

    return (0.0, 0.0, 0.0)


def neutralize_rgb_background(rgb: np.ndarray) -> np.ndarray:
    luminance = np.mean(rgb, axis=2)
    finite = np.isfinite(luminance)

    if not np.any(finite):
        return rgb

    sky_limit = np.percentile(luminance[finite], 45)
    sky_mask = finite & (luminance <= sky_limit)

    if not np.any(sky_mask):
        return rgb

    medians = np.array(
        [
            np.median(rgb[:, :, 0][sky_mask]),
            np.median(rgb[:, :, 1][sky_mask]),
            np.median(rgb[:, :, 2][sky_mask]),
        ],
        dtype=np.float32,
    )

    positive = medians[medians > 0]

    if positive.size == 0:
        return rgb

    target = float(np.median(positive))
    factors = np.ones(3, dtype=np.float32)

    for index in range(3):
        if medians[index] > 0:
            factors[index] = target / medians[index]

    factors = np.clip(factors, 0.35, 2.8)

    return np.clip(rgb * factors.reshape(1, 1, 3), 0, 1).astype(np.float32, copy=False)


def apply_visual_adjustments(
    rgb: np.ndarray,
    saturation: float,
    brightness: float,
    contrast: float,
) -> np.ndarray:
    rgb = np.clip(rgb, 0, 1)

    gray = np.mean(rgb, axis=2, keepdims=True)
    rgb = gray + (rgb - gray) * float(saturation)
    rgb = (rgb - 0.5) * float(contrast) + 0.5
    rgb = rgb + float(brightness)

    return np.clip(rgb, 0, 1).astype(np.float32, copy=False)


def output_folder_for_project(project) -> Path:
    object_folder = getattr(project, "object_folder", "") or ""

    if object_folder:
        return Path(object_folder) / "output"

    if getattr(project, "project_file", ""):
        return Path(project.project_file).parent / "output"

    return Path.cwd() / "output"


def object_name_for_project(project) -> str:
    name = getattr(project, "object_name", "") or ""

    if name:
        return name

    if getattr(project, "object_folder", ""):
        return Path(project.object_folder).name

    return "airt_output"


def build_band_masters(project) -> dict[str, np.ndarray]:
    selected = selected_object_files_by_band(project)

    if not selected:
        raise RuntimeError("No selected object frames are available.")

    calibration = selected_calibration_files(project)

    master_bias = build_master_bias(calibration)
    master_dark = build_master_dark(calibration, master_bias)

    masters: dict[str, np.ndarray] = {}

    for band in sort_bands_recommended(selected.keys()):
        master_flat = build_master_flat(calibration, band, master_bias, master_dark)
        masters[band] = stack_band_frames(
            selected[band],
            master_bias,
            master_dark,
            master_flat,
        )

    shapes = {master.shape for master in masters.values()}

    if len(shapes) != 1:
        raise RuntimeError("Master bands have incompatible dimensions.")

    # Apply manual visual offsets from screen 6 between final band masters.
    settings = project.output_options.get("alignment_settings", {}) if project else {}
    offsets = settings.get("manual_offsets", {}) or getattr(project, "manual_offsets", {}) or {}

    aligned: dict[str, np.ndarray] = {}

    for band, image in masters.items():
        offset = offsets.get(band, {})
        aligned[band] = shifted_array(
            image,
            float(offset.get("x", 0.0)),
            float(offset.get("y", 0.0)),
        )

    return aligned


def compose_final_rgb(project, masters: dict[str, np.ndarray], rendering: str, stretch: str) -> np.ndarray:
    background_settings = project.output_options.get("background_correction", {}) if project else {}
    color_mapping = project.output_options.get("color_mapping", {}) if project else {}

    corrected: dict[str, np.ndarray] = {}

    for band, master in masters.items():
        corrected[band] = correct_background_linear(master, background_settings)

    if rendering != "color":
        gray_linear = robust_median_stack(list(corrected.values()))
        gray = final_stretch_channel(gray_linear, stretch)
        return np.dstack([gray, gray, gray]).astype(np.float32, copy=False)

    shape = next(iter(corrected.values())).shape
    linear_rgb = np.zeros((shape[0], shape[1], 3), dtype=np.float32)
    weights_sum = np.zeros(3, dtype=np.float32)
    luminance = None

    for band in sort_bands_recommended(corrected.keys()):
        image = corrected[band]
        channel = channel_for_band(band, color_mapping)

        if channel == "L":
            luminance = image if luminance is None else np.nanmaximum(luminance, image)
            continue

        weights = channel_weights(channel)

        for index, weight in enumerate(weights):
            if weight > 0:
                linear_rgb[:, :, index] += image * weight
                weights_sum[index] += weight

    if np.all(weights_sum == 0):
        gray_linear = luminance if luminance is not None else robust_median_stack(list(corrected.values()))
        gray = final_stretch_channel(gray_linear, stretch)
        return np.dstack([gray, gray, gray]).astype(np.float32, copy=False)

    for index in range(3):
        if weights_sum[index] > 0:
            linear_rgb[:, :, index] /= weights_sum[index]

    stretched_rgb = np.zeros_like(linear_rgb, dtype=np.float32)

    for index in range(3):
        if weights_sum[index] > 0:
            stretched_rgb[:, :, index] = final_stretch_channel(linear_rgb[:, :, index], stretch)

    stretched_rgb = neutralize_rgb_background(stretched_rgb)

    if luminance is not None:
        luma = final_stretch_channel(luminance, stretch)
        max_channel = np.max(stretched_rgb, axis=2, keepdims=True)

        chroma = np.divide(
            stretched_rgb,
            np.maximum(max_channel, 1e-6),
            out=np.zeros_like(stretched_rgb),
            where=max_channel > 1e-6,
        )

        stretched_rgb = np.where(
            max_channel > 1e-6,
            chroma * luma[:, :, None],
            np.dstack([luma, luma, luma]),
        )

    return np.clip(stretched_rgb, 0, 1).astype(np.float32, copy=False)


def build_final_image(project, settings: dict | None = None) -> FinalRenderResult:
    settings = settings or {}
    composition = project.output_options.get("final_composition", {}) if project else {}

    rendering = settings.get("rendering", composition.get("rendering", "color"))
    stretch = settings.get("stretch", composition.get("stretch", "auto"))
    saturation = float(settings.get("saturation", composition.get("saturation", 1.0)))
    brightness = float(settings.get("brightness", composition.get("brightness", 0.0)))
    contrast = float(settings.get("contrast", composition.get("contrast", 1.0)))

    masters = build_band_masters(project)
    rgb = compose_final_rgb(project, masters, rendering, stretch)
    rgb = apply_visual_adjustments(rgb, saturation, brightness, contrast)

    return FinalRenderResult(
        image=np.clip(rgb, 0, 1),
        bands=sort_bands_recommended(masters.keys()),
        mode=rendering,
        masters=masters,
    )


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    image8 = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    image8 = np.ascontiguousarray(image8)

    height, width, _ = image8.shape
    bytes_per_line = image8.strides[0]

    return QImage(
        image8.data,
        width,
        height,
        bytes_per_line,
        QImage.Format_RGB888,
    ).copy()


def save_final_outputs(project, result: FinalRenderResult, export_settings: dict) -> list[Path]:
    output_dir = output_folder_for_project(project)
    output_dir.mkdir(parents=True, exist_ok=True)

    debug_dir = output_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    base_name = export_settings.get("file_base_name") or object_name_for_project(project)
    formats = export_settings.get("formats", {})

    generated: list[Path] = []
    qimage = rgb_to_qimage(result.image)

    if formats.get("png", True):
        path = output_dir / f"{base_name}.png"

        if not qimage.save(str(path), "PNG"):
            raise RuntimeError(f"Could not save {path}")

        generated.append(path)

    if formats.get("jpeg", False):
        path = output_dir / f"{base_name}.jpg"
        quality = int(export_settings.get("jpeg_quality", 95))

        if not qimage.save(str(path), "JPG", quality):
            raise RuntimeError(f"Could not save {path}")

        generated.append(path)

    if formats.get("tiff", True):
        path = output_dir / f"{base_name}.tif"

        if not qimage.save(str(path), "TIFF"):
            if not qimage.save(str(path), "TIF"):
                raise RuntimeError(f"Could not save {path}")

        generated.append(path)

    from astropy.io import fits

    if formats.get("fits", False):
        path = output_dir / f"{base_name}_final.fits"
        data = np.moveaxis(result.image.astype(np.float32), 2, 0)
        fits.writeto(path, data, overwrite=True)
        generated.append(path)

    # Always keep masters for now while we validate quality.
    for band, master in result.masters.items():
        safe_band = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(band))
        path = debug_dir / f"{base_name}_{safe_band}_master.fits"
        fits.writeto(path, master.astype(np.float32), overwrite=True)
        generated.append(path)

    log_path = debug_dir / "processing_log.txt"
    log_path.write_text(
        "\\n".join(
            [
                f"Object: {object_name_for_project(project)}",
                f"Mode: {result.mode}",
                f"Bands: {', '.join(result.bands)}",
                f"Output: {output_dir}",
                "Pipeline: calibrate -> align -> stack -> background correction -> compose -> stretch -> export",
            ]
        ),
        encoding="utf-8",
    )
    generated.append(log_path)

    return generated
