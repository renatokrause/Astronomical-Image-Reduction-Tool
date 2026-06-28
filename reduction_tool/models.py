from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


FILTERS = ("B", "V", "R", "I")


@dataclass(frozen=True)
class ProjectPaths:
    """Input and output folders used by one reduction project."""

    base_dir: Path
    bias_dir: Path
    flat_dir: Path
    object_dir: Path
    output_dir: Path

    @classmethod
    def from_base(cls, base_dir: Path) -> "ProjectPaths":
        return cls(
            base_dir=base_dir,
            bias_dir=base_dir / "bias",
            flat_dir=base_dir / "flat",
            object_dir=base_dir / "object",
            output_dir=base_dir / "output",
        )


@dataclass
class FileInventory:
    """FITS files found in the project folders."""

    bias: list[Path] = field(default_factory=list)
    flats: dict[str, list[Path]] = field(default_factory=dict)
    objects: dict[str, list[Path]] = field(default_factory=dict)

    def counts_by_filter(self) -> dict[str, tuple[int, int]]:
        return {
            band: (
                len(self.flats.get(band, [])),
                len(self.objects.get(band, [])),
            )
            for band in FILTERS
        }
