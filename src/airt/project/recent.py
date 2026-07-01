from __future__ import annotations

from pathlib import Path
import ctypes
import json
import os
import sys


MAX_RECENT_PROJECTS = 5


def app_state_dir() -> Path:
    path = Path.home() / ".airt"
    path.mkdir(parents=True, exist_ok=True)
    return path


def recent_projects_file() -> Path:
    return app_state_dir() / "recent_projects.json"


def windows_documents_dir() -> Path | None:
    if sys.platform != "win32":
        return None

    # FOLDERID_Documents
    folderid_documents = ctypes.c_char * 16
    folderid = folderid_documents(
        0xFDD39AD0.to_bytes(4, "little")
        + 0x238F.to_bytes(2, "little")
        + 0x46AF.to_bytes(2, "big")
        + bytes.fromhex("ADB4 6C85480369C7".replace(" ", ""))
    )

    path_ptr = ctypes.c_wchar_p()

    try:
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folderid),
            0,
            None,
            ctypes.byref(path_ptr),
        )

        if result == 0 and path_ptr.value:
            return Path(path_ptr.value)
    except Exception:
        return None

    return None


def user_documents_dir() -> Path:
    win_docs = windows_documents_dir()
    if win_docs and win_docs.exists():
        return win_docs

    candidates = [
        Path.home() / "Documents",
        Path.home() / "Documentos",
        Path(os.environ.get("USERPROFILE", "")) / "Documents",
        Path(os.environ.get("USERPROFILE", "")) / "Documentos",
    ]

    for candidate in candidates:
        if str(candidate).strip() and candidate.exists():
            return candidate

    return Path.home()


def default_projects_dir() -> Path:
    path = user_documents_dir() / "AIRT-projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


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
