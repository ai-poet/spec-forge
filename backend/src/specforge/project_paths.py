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


def default_browse_path() -> Path:
    home = Path.home()
    for candidate in (Path.cwd(), home / "Projects", home / "Desktop", home):
        try:
            resolved = candidate.expanduser().resolve()
            if resolved.is_dir():
                return resolved
        except OSError:
            continue
    return home.resolve()


def resolve_browse_path(path: str | None) -> Path:
    target = Path(path).expanduser() if path else default_browse_path()
    if not target.is_absolute():
        target = target.resolve()
    else:
        target = target.resolve()
    if not target.exists():
        raise ProjectPathError("path does not exist")
    if not target.is_dir():
        raise ProjectPathError("path is not a directory")
    return target


def browse_directory(path: str | None = None) -> dict[str, object]:
    current = resolve_browse_path(path)
    parent = str(current.parent) if current.parent != current else None
    entries: list[dict[str, str]] = []
    try:
        children = sorted(current.iterdir(), key=lambda item: item.name.lower())
    except OSError as exc:
        raise ProjectPathError(f"cannot read directory: {exc}") from exc

    for child in children:
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        try:
            entries.append({"name": child.name, "path": str(child.resolve())})
        except OSError:
            continue

    quick_roots: list[dict[str, str]] = []
    home = Path.home().resolve()
    for label, candidate in (
        ("主目录", home),
        ("桌面", home / "Desktop"),
        ("文档", home / "Documents"),
        ("下载", home / "Downloads"),
        ("当前工作目录", Path.cwd()),
    ):
        try:
            resolved = candidate.expanduser().resolve()
            if resolved.is_dir():
                quick_roots.append({"label": label, "path": str(resolved)})
        except OSError:
            continue

    return {
        "path": str(current),
        "parent": parent,
        "entries": entries,
        "quick_roots": quick_roots,
    }
