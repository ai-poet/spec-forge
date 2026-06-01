from __future__ import annotations

import sys
import time
from threading import Thread

from specforge.agents.cli_runner import RealCLIRunner


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
