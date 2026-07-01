from __future__ import annotations

from pathlib import Path
import json


MAX_RECENT_PROJECTS = 10


def app_state_dir() -> Path:
    path = Path.home() / ".airt"
    path.mkdir(parents=True, exist_ok=True)
    return path


def recent_projects_file() -> Path:
    return app_state_dir() / "recent_projects.json"


def default_projects_dir() -> Path:
    # User-requested default location on Windows/Portuguese systems.
    preferred = Path.home() / "Documentos" / "AIRT-projects"
    preferred.mkdir(parents=True, exist_ok=True)
    return preferred


def load_recent_projects() -> list[dict[str, str]]:
    path = recent_projects_file()

    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    result: list[dict[str, str]] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        project_path = str(item.get("path", "")).strip()
        project_name = str(item.get("name", "")).strip()

        if not project_path:
            continue

        if not Path(project_path).exists():
            continue

        result.append(
            {
                "path": project_path,
                "name": project_name or Path(project_path).stem,
            }
        )

    return result[:MAX_RECENT_PROJECTS]


def save_recent_projects(items: list[dict[str, str]]) -> None:
    path = recent_projects_file()
    path.write_text(
        json.dumps(items[:MAX_RECENT_PROJECTS], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_recent_project(project_path: str, name: str | None = None) -> None:
    if not project_path:
        return

    resolved = str(Path(project_path).expanduser().resolve())
    display_name = name or Path(resolved).stem

    existing = load_recent_projects()

    filtered = [
        item for item in existing
        if str(Path(item["path"]).expanduser().resolve()) != resolved
    ]

    filtered.insert(
        0,
        {
            "path": resolved,
            "name": display_name,
        },
    )

    save_recent_projects(filtered)
