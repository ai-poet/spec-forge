from __future__ import annotations

from specforge.ui_runtime import log_ui_runtime_status, ui_runtime_status


def test_ui_runtime_status_shape() -> None:
    status = ui_runtime_status()
    assert "playwright" in status
    assert "cua" in status
    assert "install_hint" in status
    assert "pip install" in status["install_hint"]


def test_log_ui_runtime_status_returns_same_payload(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO)
    status = log_ui_runtime_status()
    assert status["playwright"]
    assert any("UI runtime" in record.message for record in caplog.records)
