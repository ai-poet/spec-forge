from __future__ import annotations

from pathlib import Path

from specforge import cua_bootstrap


def test_cua_driver_installed_detects_app_bundle(tmp_path: Path, monkeypatch) -> None:
    fake_app = tmp_path / "CuaDriver.app"
    fake_app.mkdir()
    monkeypatch.setattr(cua_bootstrap, "SWIFT_APP_BUNDLE", fake_app)
    monkeypatch.setattr(cua_bootstrap, "RS_APP_BUNDLE", tmp_path / "missing.app")
    monkeypatch.setattr(cua_bootstrap, "RS_HOME_DIR", tmp_path / "missing-rs")
    assert cua_bootstrap.cua_driver_installed() is True


def test_ensure_cua_driver_skips_when_installed(monkeypatch) -> None:
    monkeypatch.setattr(cua_bootstrap, "cua_driver_installed", lambda: True)
    assert cua_bootstrap.ensure_cua_driver() is None


def test_ensure_cua_driver_runs_install_script(monkeypatch, tmp_path: Path) -> None:
    script = tmp_path / "install_cua_driver.py"
    script.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(cua_bootstrap, "INSTALL_SCRIPT", script)
    installed = {"value": False}

    def installed_fn() -> bool:
        return installed["value"]

    def fake_run(cmd, **kwargs):
        installed["value"] = True

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(cua_bootstrap, "cua_driver_installed", installed_fn)
    monkeypatch.setattr(cua_bootstrap.subprocess, "run", fake_run)
    assert cua_bootstrap.ensure_cua_driver() is None
    assert installed["value"]


def test_ensure_cua_driver_no_auto_install_returns_hint(monkeypatch) -> None:
    monkeypatch.setattr(cua_bootstrap, "cua_driver_installed", lambda: False)
    error = cua_bootstrap.ensure_cua_driver(auto_install=False)
    assert error is not None
    assert "install_cua_driver" in error
