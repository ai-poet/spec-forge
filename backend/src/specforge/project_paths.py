from __future__ import annotations

from pathlib import Path


class ProjectPathError(ValueError):
    pass


def prepare_project_root(root_path: str, create_if_missing: bool) -> Path:
    path = Path(root_path).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    else:
        path = path.resolve()

    if path.exists():
        if not path.is_dir():
            raise ProjectPathError("path exists but is not a directory")
    elif create_if_missing:
        path.mkdir(parents=True, exist_ok=True)
    else:
        raise ProjectPathError("path does not exist")

    probe = path / ".specforge_write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ProjectPathError(f"path is not writable: {exc}") from exc

    return path


def validate_project_root(root_path: str, create_if_missing: bool) -> dict[str, str | bool]:
    try:
        resolved = prepare_project_root(root_path, create_if_missing)
        return {"ok": True, "resolved_path": str(resolved), "message": "path is available"}
    except ProjectPathError as exc:
        return {"ok": False, "resolved_path": "", "message": str(exc)}
