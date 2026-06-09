from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread

from specforge.agents.cli_runner import RealCLIRunner


def wait_for_registry_entry(path: Path, iteration_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            entry = payload.get(iteration_id)
            if entry:
                return entry
        time.sleep(0.05)
    raise AssertionError("registry entry was not written")


def test_real_cli_runner_streams_stdout_and_stderr():
    chunks: list[tuple[str, str]] = []
    runner = RealCLIRunner()

    result = runner.run(
        [
            sys.executable,
            "-c",
            "import sys; print('visible stdout'); print('visible stderr', file=sys.stderr)",
        ],
        on_output=lambda stream, chunk: chunks.append((stream, chunk)),
    )

    assert result.returncode == 0
    assert "visible stdout" in result.stdout
    assert "visible stderr" in result.stderr
    assert any(stream == "stdout" and "visible stdout" in chunk for stream, chunk in chunks)
    assert any(stream == "stderr" and "visible stderr" in chunk for stream, chunk in chunks)


def test_real_cli_runner_keeps_bounded_stdout_tail():
    runner = RealCLIRunner()

    result = runner.run(
        [
            sys.executable,
            "-c",
            "print('x' * 1000)",
        ],
        capture_max_chars=128,
    )

    assert result.returncode == 0
    assert len(result.stdout) <= 128
    assert result.stdout.endswith("\n")
    assert result.stdout_bytes > len(result.stdout.encode("utf-8"))
    assert result.metadata["stdout_truncated"] is True


def test_real_cli_runner_cancel_terminates_active_process():
    runner = RealCLIRunner()
    iteration_id = "cancel-me"
    results: list = []

    def run_process() -> None:
        results.append(
            runner.run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                iteration_id=iteration_id,
            )
        )

    thread = Thread(target=run_process, daemon=True)
    thread.start()
    time.sleep(0.3)
    assert runner.cancel(iteration_id) is True
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert results
    assert results[0].returncode != 0


def test_real_cli_runner_registry_tracks_and_clears_active_process(tmp_path):
    registry_path = tmp_path / "active_cli.json"
    runner = RealCLIRunner(registry_path=registry_path)
    iteration_id = "registry-cancel"
    results: list = []

    def run_process() -> None:
        results.append(
            runner.run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                iteration_id=iteration_id,
            )
        )

    thread = Thread(target=run_process, daemon=True)
    thread.start()
    entry = wait_for_registry_entry(registry_path, iteration_id)

    assert entry["pid"] > 0
    assert runner.cancel(iteration_id) is True
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert not registry_path.exists()
    assert results
    assert results[0].returncode != 0


def test_real_cli_runner_cleanup_registry_processes_terminates_leftover_process(tmp_path):
    registry_path = tmp_path / "active_cli.json"
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    try:
        registry_path.write_text(
            json.dumps(
                {
                    "iter-leftover": {
                        "pid": proc.pid,
                        "pgid": os.getpgid(proc.pid),
                        "command": ["python", "sleep"],
                    }
                }
            ),
            encoding="utf-8",
        )
        runner = RealCLIRunner(registry_path=registry_path)

        assert runner.cleanup_registry_processes() == ["iter-leftover"]
        proc.wait(timeout=5)
        assert proc.returncode != 0
        assert not registry_path.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
