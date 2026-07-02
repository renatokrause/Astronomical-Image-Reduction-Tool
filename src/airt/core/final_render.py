from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np

from PySide6.QtGui import QImage


@dataclass
class FinalRenderResult:
    image: np.ndarray
    bands: list[str]
    mode: str


def selected_object_files_by_band(project) -> dict[str, list[str]]:
    if not project:
        return {}

    return {
        band: list(paths)
        for band, paths in getattr(project, "selected_object_files", {}).items()
        if band and band != "-" and paths
    }


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

    return data.astype(np.float32, copy=False)


def normalize_array(data: np.ndarray) -> np.ndarray:
    finite = np.isfinite(data)

    if not np.any(finite):
        return np.zeros_like(data, dtype=np.float32)

    valid = data[finite]
    low, high = np.percentile(valid, [1, 99.5])

    if high <= low:
        low = float(np.min(valid))
        high = float(np.max(valid))

    if high <= low:
        high = low + 1.0

    stretched = (data - low) / (high - low)
    stretched = np.clip(stretched, 0, 1)
    stretched[~finite] = 0

    return stretched.astype(np.float32, copy=False)


def shifted_array(image: np.ndarray, x: float, y: float) -> np.ndarray:
    try:
        from scipy.ndimage import shift

        return shift(
            image,
            shift=(y, x),
            order=1,
            mode="constant",
            cval=0.0,
            prefilter=False,
        ).astype(np.float32, copy=False)
    except Exception:
        return np.roll(image, shift=(int(round(y)), int(round(x))), axis=(0, 1))


def default_channel_for_band(band: str) -> str:
    text = str(band).strip().upper().replace(" ", "").replace("-", "").replace("_", "")

    if text in {"L", "LUM", "LUMINANCE", "CLEAR", "C"}:
        return "L"

    if text in {"R", "RED", "HA", "HALPHA", "SII", "S2", "I", "IR", "INFRARED"}:
        return "R"

    if text in {"G", "GREEN", "V"}:
        return "G"

    if text in {"B", "BLUE", "HB", "HBETA", "OIII", "O3"}:
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


def stretch_channel(channel: np.ndarray, stretch: str) -> np.ndarray:
    finite = np.isfinite(channel)

    if not np.any(finite):
        return np.zeros_like(channel, dtype=np.float32)

    valid = channel[finite]

    if stretch == "linear":
        low, high = np.percentile(valid, [1, 99.5])
        gamma = 1.0
    elif stretch == "soft":
        low, high = np.percentile(valid, [1, 99.7])
        gamma = 0.75
    elif stretch == "strong":
        low, high = np.percentile(valid, [0.5, 99.8])
        gamma = 0.45
    else:
        low, high = np.percentile(valid, [1, 99.7])
        gamma = 0.60

    if high <= low:
        low = float(np.min(valid))
        high = float(np.max(valid))

    if high <= low:
        high = low + 1.0

    out = (channel - low) / (high - low)
    out = np.clip(out, 0, 1)
    out[~finite] = 0

    if gamma != 1.0:
        out = np.power(out, gamma)

    return out.astype(np.float32, copy=False)


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


def estimate_background(image: np.ndarray, block_size: int, protection: str) -> np.ndarray:
    height, width = image.shape
    block_size = max(8, int(block_size))

    pad_h = (block_size - height % block_size) % block_size
    pad_w = (block_size - width % block_size) % block_size

    padded = np.pad(image, ((0, pad_h), (0, pad_w)), mode="edge")

    if protection == "low":
        percentile = 90.0
    elif protection == "high":
        percentile = 70.0
    else:
        percentile = 80.0

    threshold = np.percentile(padded, percentile)
    protected = np.where(padded <= threshold, padded, np.nan)

    h2, w2 = padded.shape

    blocks = protected.reshape(
        h2 // block_size,
        block_size,
        w2 // block_size,
        block_size,
    )

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

        background = gaussian_filter(background, sigma=max(1.0, block_size / 3.0))
    except Exception:
        pass

    return background.astype(np.float32, copy=False)


def apply_background_correction(image: np.ndarray, settings: dict) -> np.ndarray:
    if not settings or not settings.get("enabled", False):
        return image

    strength = float(settings.get("strength", 0.35))
    scale = int(settings.get("scale", 128))
    protection = settings.get("object_protection", "medium")

    if image.ndim == 2:
        background = estimate_background(image, scale, protection)
        variation = background - float(np.nanmedian(background))
        return np.clip(image - strength * variation, 0, 1).astype(np.float32, copy=False)

    corrected = np.zeros_like(image, dtype=np.float32)

    for index in range(3):
        channel = image[:, :, index]
        background = estimate_background(channel, scale, protection)
        variation = background - float(np.nanmedian(background))
        corrected[:, :, index] = channel - strength * variation

    return np.clip(corrected, 0, 1).astype(np.float32, copy=False)


def load_band_masters(project) -> dict[str, np.ndarray]:
    selected = selected_object_files_by_band(project)
    result = {}

    for band, paths in selected.items():
        arrays = []

        for path_text in paths:
            path = Path(path_text)

            if not path.exists():
                continue

            try:
                arrays.append(load_fits_array(path))
            except Exception:
                continue

        if not arrays:
            continue

        reference_shape = arrays[0].shape
        arrays = [array for array in arrays if array.shape == reference_shape]

        if not arrays:
            continue

        combined = arrays[0] if len(arrays) == 1 else np.nanmedian(np.stack(arrays, axis=0), axis=0)
        result[band] = normalize_array(combined)

    return result


def build_final_image(project, settings: dict | None = None) -> FinalRenderResult:
    settings = settings or {}
    composition = project.output_options.get("final_composition", {}) if project else {}

    rendering = settings.get("rendering", composition.get("rendering", "grayscale"))
    stretch = settings.get("stretch", composition.get("stretch", "auto"))
    saturation = float(settings.get("saturation", composition.get("saturation", 1.0)))
    brightness = float(settings.get("brightness", composition.get("brightness", 0.0)))
    contrast = float(settings.get("contrast", composition.get("contrast", 1.0)))

    band_arrays = load_band_masters(project)

    if not band_arrays:
        raise RuntimeError("No selected object bands are available for final rendering.")

    shapes = {array.shape for array in band_arrays.values()}

    if len(shapes) != 1:
        raise RuntimeError("Selected bands have incompatible dimensions.")

    alignment_settings = project.output_options.get("alignment_settings", {}) if project else {}
    offsets = alignment_settings.get("manual_offsets", {}) or getattr(project, "manual_offsets", {}) or {}

    background_settings = project.output_options.get("background_correction", {}) if project else {}
    color_mapping = project.output_options.get("color_mapping", {}) if project else {}

    bands = list(band_arrays.keys())

    shifted = {}

    for band, image in band_arrays.items():
        offset = offsets.get(band, {})
        shifted[band] = shifted_array(
            image,
            float(offset.get("x", 0.0)),
            float(offset.get("y", 0.0)),
        )

    if rendering == "color":
        height, width = next(iter(shapes))
        rgb = np.zeros((height, width, 3), dtype=np.float32)
        weights_sum = np.zeros(3, dtype=np.float32)

        for band, image in shifted.items():
            mapping = color_mapping.get(band, {})
            channel = mapping.get("channel") or default_channel_for_band(band)

            if channel == "L":
                continue

            weights = channel_weights(channel)

            for index, weight in enumerate(weights):
                if weight > 0:
                    rgb[:, :, index] += image * float(weight)
                    weights_sum[index] += float(weight)

        if np.all(weights_sum == 0):
            rendering = "grayscale"
        else:
            for index in range(3):
                if weights_sum[index] > 0:
                    rgb[:, :, index] /= weights_sum[index]
                    rgb[:, :, index] = stretch_channel(rgb[:, :, index], stretch)

            rgb = apply_background_correction(rgb, background_settings)
            rgb = apply_visual_adjustments(rgb, saturation, brightness, contrast)

            return FinalRenderResult(image=rgb, bands=bands, mode="color")

    stacked = np.nanmedian(np.stack(list(shifted.values()), axis=0), axis=0)
    gray = stretch_channel(stacked, stretch)
    gray = apply_background_correction(gray, background_settings)
    gray_rgb = np.dstack([gray, gray, gray])
    gray_rgb = apply_visual_adjustments(gray_rgb, 0.0, brightness, contrast)

    return FinalRenderResult(image=gray_rgb, bands=bands, mode="grayscale")


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    image8 = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    image8 = np.ascontiguousarray(image8)

    height, width, channels = image8.shape
    bytes_per_line = image8.strides[0]

    return QImage(
        image8.data,
        width,
        height,
        bytes_per_line,
        QImage.Format_RGB888,
    ).copy()


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


def save_final_outputs(project, result: FinalRenderResult, export_settings: dict) -> list[Path]:
    output_dir = output_folder_for_project(project)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = export_settings.get("file_base_name") or object_name_for_project(project)
    formats = export_settings.get("formats", {})

    generated = []
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
            # Qt TIFF support can vary. Try TIF.
            if not qimage.save(str(path), "TIF"):
                raise RuntimeError(f"Could not save {path}")
        generated.append(path)

    if formats.get("fits", False):
        from astropy.io import fits

        path = output_dir / f"{base_name}_final.fits"
        data = np.moveaxis(result.image.astype(np.float32), 2, 0)
        fits.writeto(path, data, overwrite=True)
        generated.append(path)

    return generated
