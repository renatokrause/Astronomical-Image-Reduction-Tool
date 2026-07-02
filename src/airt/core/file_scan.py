from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from airt.core.bands import normalize_band_name, recommended_band_sort_key, sort_bands_recommended

FITS_EXTENSIONS = (".fit", ".fits", ".fts", ".fit.gz", ".fits.gz", ".fts.gz")


@dataclass
class FitsFileInfo:
    path: str
    kind: str
    band: str
    exptime: float | None
    naxis1: int | None
    naxis2: int | None
    binning: str
    status: str
    problem: str = ""


@dataclass
class ScanSummaryRow:
    kind: str
    band: str
    count: int
    status: str
    problems: str


@dataclass
class ScanResult:
    files: list[FitsFileInfo]
    summary: list[ScanSummaryRow]
    problems: list[str]


def is_fits_file(path: Path) -> bool:
    lower = path.name.lower()
    return any(lower.endswith(ext) for ext in FITS_EXTENSIONS)


def iter_fits_files(folder: str | None) -> Iterable[Path]:
    if not folder:
        return []

    root = Path(folder)
    if not root.exists():
        return []

    return sorted(path for path in root.rglob("*") if path.is_file() and is_fits_file(path))


def normalize_band(value: object, fallback: str = "-") -> str:
    if value is None:
        return fallback

    text = str(value).strip()
    if not text:
        return fallback

    normalized = normalize_band_name(text)
    return fallback if normalized == "UNKNOWN" else normalized


def infer_band_from_filename(path: Path) -> str:
    name = path.stem.upper()

    patterns = [
        r"(^|[_\-\s])(HA|HALPHA|H-ALPHA)([_\-\s]|$)",
        r"(^|[_\-\s])(OIII|O-III)([_\-\s]|$)",
        r"(^|[_\-\s])(SII|S-II)([_\-\s]|$)",
        r"(^|[_\-\s])([UBVRI])([_\-\s]|\d|$)",
        r"(^|[_\-\s])(L|LUM|LUMINANCE|CLEAR)([_\-\s]|\d|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, name)
        if not match:
            continue

        token = match.group(2)
        return normalize_band(token)

    return "-"


def header_value(header, names: list[str]):
    for name in names:
        if name in header:
            return header.get(name)
    return None


def read_fits_header(path: Path):
    try:
        from astropy.io import fits
    except Exception as exc:
        raise RuntimeError("Astropy is required to scan FITS files. Install it with: pip install astropy") from exc

    return fits.getheader(path, 0)


def read_one_file(path: Path, kind: str) -> FitsFileInfo:
    try:
        header = read_fits_header(path)

        filter_value = header_value(
            header,
            [
                "FILTER",
                "FILTER1",
                "FILTER2",
                "FILT",
                "BAND",
                "FILTERID",
                "FILTERID1",
                "INSFLNAM",
            ],
        )

        fallback_band = infer_band_from_filename(path)

        band = "-" if kind in {"bias", "dark"} else normalize_band(filter_value, fallback=fallback_band)

        exptime_value = header_value(header, ["EXPTIME", "EXPOSURE", "EXP_TIME", "ITIME"])
        try:
            exptime = float(exptime_value) if exptime_value is not None else None
        except Exception:
            exptime = None

        naxis1 = header.get("NAXIS1")
        naxis2 = header.get("NAXIS2")

        xbin = header_value(header, ["XBINNING", "CCDXBIN", "XBIN"])
        ybin = header_value(header, ["YBINNING", "CCDYBIN", "YBIN"])

        binning = f"{xbin or '?'}x{ybin or '?'}" if xbin is not None or ybin is not None else "-"

        problem = ""

        if kind in {"object", "flat", "focus"} and band == "-":
            problem = "Could not detect filter/band"

        if naxis1 is None or naxis2 is None:
            problem = "Missing image dimensions"

        return FitsFileInfo(
            path=str(path),
            kind=kind,
            band=band,
            exptime=exptime,
            naxis1=int(naxis1) if naxis1 is not None else None,
            naxis2=int(naxis2) if naxis2 is not None else None,
            binning=binning,
            status="OK" if not problem else "Warning",
            problem=problem,
        )

    except Exception as exc:
        return FitsFileInfo(
            path=str(path),
            kind=kind,
            band="-",
            exptime=None,
            naxis1=None,
            naxis2=None,
            binning="-",
            status="Error",
            problem=str(exc),
        )


def summarize(files: list[FitsFileInfo]) -> list[ScanSummaryRow]:
    groups: dict[tuple[str, str], list[FitsFileInfo]] = {}

    for item in files:
        key = (item.kind, item.band)
        groups.setdefault(key, []).append(item)

    rows: list[ScanSummaryRow] = []

    kind_order = {"object": 0, "bias": 1, "dark": 2, "flat": 3, "focus": 4}

    for (kind, band), group in sorted(
        groups.items(),
        key=lambda item: (kind_order.get(item[0][0], 99), recommended_band_sort_key(item[0][1])),
    ):
        problems = sorted({item.problem for item in group if item.problem})
        status = "OK" if not problems else "Warning"

        if any(item.status == "Error" for item in group):
            status = "Error"

        rows.append(
            ScanSummaryRow(
                kind=kind,
                band=band,
                count=len(group),
                status=status,
                problems="; ".join(problems),
            )
        )

    return rows


def scan_project_files(project, progress_callback=None) -> ScanResult:
    def existing_folder(*paths):
        for value in paths:
            if not value:
                continue
            path = Path(value)
            if path.exists():
                return str(path)
        return str(Path(paths[0])) if paths and paths[0] else ""

    object_folder = getattr(project, "object_folder", "")
    lights_folder = getattr(project, "lights_folder", "")

    # Prefer <object>/lights when it exists and has FITS files.
    # Otherwise scan the object folder itself.
    resolved_lights_folder = ""
    if lights_folder and Path(lights_folder).exists() and list(iter_fits_files(lights_folder)):
        resolved_lights_folder = lights_folder
    elif object_folder and Path(object_folder).exists():
        resolved_lights_folder = object_folder
    else:
        resolved_lights_folder = lights_folder or object_folder

    flat_folder = getattr(project, "flats_folder", "")
    if flat_folder and not Path(flat_folder).exists():
        candidate = Path(flat_folder)
        if candidate.name.lower() == "flats":
            singular = candidate.parent / "flat"
            if singular.exists():
                flat_folder = str(singular)
        elif candidate.name.lower() == "flat":
            plural = candidate.parent / "flats"
            if plural.exists():
                flat_folder = str(plural)

    folders = [
        ("bias", getattr(project, "bias_folder", "")),
        ("dark", getattr(project, "dark_folder", "")),
        ("flat", flat_folder),
        ("focus", getattr(project, "focus_folder", "")),
        ("object", resolved_lights_folder),
    ]

    candidates: list[tuple[str, Path]] = []

    for kind, folder in folders:
        for path in iter_fits_files(folder):
            # Avoid treating project JSON, outputs, debug products, or calibration subfolders as lights
            if kind == "object":
                lower_parts = {part.lower() for part in path.parts}
                if {"output", "debug", "calibration", "bias", "dark", "flat", "flats", "focus"} & lower_parts:
                    continue
            candidates.append((kind, path))

    total = len(candidates)
    files: list[FitsFileInfo] = []

    if progress_callback:
        progress_callback(0, max(total, 1), "Preparing scan")

    for index, (kind, path) in enumerate(candidates, start=1):
        if progress_callback:
            progress_callback(index - 1, max(total, 1), f"Reading {path.name}")

        files.append(read_one_file(path, kind))

        if progress_callback:
            progress_callback(index, max(total, 1), f"Read {path.name}")

    summary = summarize(files)

    problems: list[str] = []

    configured_folders = {kind: folder for kind, folder in folders}

    for kind, folder in configured_folders.items():
        if not folder:
            problems.append(f"{kind}: folder not configured")
        elif not Path(folder).exists():
            problems.append(f"{kind}: folder does not exist: {folder}")

    light_bands = sort_bands_recommended({item.band for item in files if item.kind == "object" and item.band != "-"})
    flat_bands = sort_bands_recommended({item.band for item in files if item.kind == "flat" and item.band != "-"})

    for band in light_bands:
        if band not in flat_bands:
            problems.append(f"Object band {band} has no matching flat band")

    if not any(item.kind == "object" for item in files):
        problems.append("No object FITS files found")

    if not any(item.kind == "bias" for item in files):
        problems.append("No bias FITS files found")

    if not any(item.kind == "flat" for item in files):
        problems.append("No flat FITS files found")

    file_problems = [f"{Path(item.path).name}: {item.problem}" for item in files if item.problem]

    problems.extend(file_problems)

    return ScanResult(files=files, summary=summary, problems=problems)
