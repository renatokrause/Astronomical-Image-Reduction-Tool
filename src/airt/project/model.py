from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class ReductionProject:
    object_name: str = ""
    project_root: str = ""
    object_folder: str = ""
    project_file: str = ""

    lights_folder: str = ""
    bias_folder: str = ""
    dark_folder: str = ""
    flats_folder: str = ""
    focus_folder: str = ""
    output_folder: str = ""

    selected_object_files: dict[str, list[str]] = field(default_factory=dict)
    rejected_object_files: dict[str, list[str]] = field(default_factory=dict)
    selected_calibration_files: dict[str, list[str]] = field(default_factory=dict)
    rejected_calibration_files: dict[str, list[str]] = field(default_factory=dict)

    preset: str = "auto"
    alignment_mode: str = "automatic"
    manual_offsets: dict[str, dict[str, float]] = field(default_factory=dict)

    background_params: dict[str, Any] = field(default_factory=dict)
    object_mask_params: dict[str, Any] = field(default_factory=dict)
    crop_params: dict[str, Any] = field(default_factory=dict)
    stretch_params: dict[str, Any] = field(default_factory=dict)
    output_options: dict[str, Any] = field(default_factory=dict)

    last_completed_step: str = "welcome"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    dirty: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReductionProject:
        known_fields = {field.name for field in cls.__dataclass_fields__.values()}
        filtered = {key: value for key, value in data.items() if key in known_fields}
        return cls(**filtered)

    def update_timestamp(self) -> None:
        self.updated_at = now_iso()
        self.dirty = True


def apply_standard_folder_structure(project: ReductionProject) -> None:
    root = Path(project.project_root).expanduser()
    object_name = project.object_name.strip()

    if not object_name:
        return

    object_folder = root / object_name

    project.object_folder = str(object_folder)
    project.project_file = str(object_folder / f"{object_name}.airt.json")
    project.lights_folder = str(object_folder / "lights")
    project.output_folder = str(object_folder / "output")

    project.bias_folder = str(root / "calibration" / "bias")
    project.dark_folder = str(root / "calibration" / "dark")
    project.flats_folder = str(root / "calibration" / "flats")
    project.focus_folder = str(root / "calibration" / "focus")

    project.update_timestamp()
