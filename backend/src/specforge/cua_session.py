from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import settings

_PROCESS_LOCK = threading.Lock()

CUA_BUSY_SINGLE_SESSION_PREFIX = "CuaDriver busy: only one UI session allowed"


@dataclass(frozen=True)
class CuaSessionHolder:
    iteration_id: str
    pid: int


def cua_session_lock_path() -> Path:
    return settings.data_dir / "cua-driver.session.lock"


def cua_session_busy_message(holder_iteration_id: str | None) -> str:
    who = holder_iteration_id or "another task"
    return (
        f"{CUA_BUSY_SINGLE_SESSION_PREFIX} (held by {who}); "
        "use Playwright for web when possible, otherwise rely on Tester code review."
    )


def read_cua_session_holder() -> CuaSessionHolder | None:
    path = cua_session_lock_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        iteration_id = str(payload.get("iteration_id") or "")
        pid = int(payload["pid"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if not _pid_alive(pid):
        _clear_stale_lock(path)
        return None
    return CuaSessionHolder(iteration_id=iteration_id, pid=pid)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _clear_stale_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _try_file_lock(path: Path) -> tuple[object | None, bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (ImportError, BlockingIOError, OSError):
        handle.close()
        return None, False
    return handle, True


def _release_file_lock(handle: object | None, path: Path) -> None:
    if handle is None:
        return
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (ImportError, OSError):
        pass
    try:
        handle.close()  # type: ignore[union-attr]
    except OSError:
        pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@contextmanager
def try_acquire_cua_session(iteration_id: str) -> Iterator[CuaSessionHolder | None]:
    """Acquire global CUA session lock (non-blocking). Yields None when busy."""
    path = cua_session_lock_path()
    handle: object | None = None
    acquired = False
    session: CuaSessionHolder | None = None

    with _PROCESS_LOCK:
        existing = read_cua_session_holder()
        if existing is not None and existing.pid != os.getpid():
            yield None
            return
        handle, acquired = _try_file_lock(path)
        if not acquired:
            yield None
            return
        metadata = {
            "iteration_id": iteration_id,
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        assert handle is not None
        handle.seek(0)  # type: ignore[union-attr]
        handle.truncate()  # type: ignore[union-attr]
        handle.write(json.dumps(metadata, ensure_ascii=False))  # type: ignore[union-attr]
        handle.flush()  # type: ignore[union-attr]
        session = CuaSessionHolder(iteration_id=iteration_id, pid=os.getpid())

    try:
        yield session
    finally:
        if acquired:
            _release_file_lock(handle, path)
