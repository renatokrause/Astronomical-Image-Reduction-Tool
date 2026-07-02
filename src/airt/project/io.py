from __future__ import annotations

import json
from pathlib import Path

from airt.project.model import ReductionProject


def save_project(project: ReductionProject) -> None:
    if not project.project_file:
        raise ValueError("Project file is not defined.")

    path = Path(project.project_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    project.update_timestamp()
    data = {
        "schema": "airt.project",
        "schema_version": 1,
        "project": project.to_dict(),
    }

    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    project.dirty = False


def load_project(path: str | Path) -> ReductionProject:
    project_path = Path(path)
    data = json.loads(project_path.read_text(encoding="utf-8"))

    project = ReductionProject.from_dict(data["project"]) if "project" in data else ReductionProject.from_dict(data)

    project.project_file = str(project_path)
    project.dirty = False
    return project


def autosave_project(project: ReductionProject) -> bool:
    if not project.project_file:
        return False

    save_project(project)
    return True
