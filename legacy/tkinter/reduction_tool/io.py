from __future__ import annotations

from pathlib import Path

from .models import FILTERS, FileInventory, ProjectPaths


FITS_PATTERNS = ("*.fits", "*.fit", "*.fts", "*.FITS", "*.FIT", "*.FTS")


def find_fits_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []

    files: list[Path] = []
    for pattern in FITS_PATTERNS:
        files.extend(folder.glob(pattern))
    return sorted(set(files))


def detect_filter(file_path: Path) -> str | None:
    name = file_path.name.upper()
    for band in FILTERS:
        if f"_{band}_" in name or name.endswith(f"{band}.FITS") or name.endswith(f"{band}.FIT"):
            return band
    return None


def group_by_filter(files: list[Path]) -> dict[str, list[Path]]:
    grouped = {band: [] for band in FILTERS}
    for file_path in files:
        band = detect_filter(file_path)
        if band:
            grouped[band].append(file_path)
    return grouped


def scan_project(paths: ProjectPaths) -> FileInventory:
    return FileInventory(
        bias=find_fits_files(paths.bias_dir),
        flats=group_by_filter(find_fits_files(paths.flat_dir)),
        objects=group_by_filter(find_fits_files(paths.object_dir)),
    )
