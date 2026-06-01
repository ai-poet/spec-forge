from __future__ import annotations

import json
from pathlib import Path

from specforge import cua_session


def test_read_holder_after_acquire(tmp_path: Path, monkeypatch) -> None:
    lock_path = tmp_path / "cua-driver.session.lock"
    monkeypatch.setattr(cua_session, "cua_session_lock_path", lambda: lock_path)

    with cua_session.try_acquire_cua_session("iter-a") as session:
        assert session is not None
        assert session.iteration_id == "iter-a"
        holder = cua_session.read_cua_session_holder()
        assert holder is not None
        assert holder.iteration_id == "iter-a"

    assert cua_session.read_cua_session_holder() is None


def test_second_acquire_non_blocking_fails(tmp_path: Path, monkeypatch) -> None:
    lock_path = tmp_path / "cua-driver.session.lock"
    monkeypatch.setattr(cua_session, "cua_session_lock_path", lambda: lock_path)

    with cua_session.try_acquire_cua_session("iter-a") as first:
        assert first is not None
        with cua_session.try_acquire_cua_session("iter-b") as second:
            assert second is None
        holder = cua_session.read_cua_session_holder()
        assert holder is not None
        assert holder.iteration_id == "iter-a"


def test_busy_message_includes_holder() -> None:
    message = cua_session.cua_session_busy_message("iter-xyz")
    assert "iter-xyz" in message
    assert cua_session.CUA_BUSY_SINGLE_SESSION_PREFIX in message


def test_stale_lock_cleared_when_pid_dead(tmp_path: Path, monkeypatch) -> None:
    lock_path = tmp_path / "cua-driver.session.lock"
    monkeypatch.setattr(cua_session, "cua_session_lock_path", lambda: lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"iteration_id": "stale", "pid": 999999999}),
        encoding="utf-8",
    )
    assert cua_session.read_cua_session_holder() is None
