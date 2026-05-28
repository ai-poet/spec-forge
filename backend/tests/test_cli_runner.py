from __future__ import annotations

import sys

from specforge.cli_runner import RealCLIRunner


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
