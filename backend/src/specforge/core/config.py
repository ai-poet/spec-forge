from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    app_name: str = "SpecForge"
    host: str = "127.0.0.1"
    port: int = 8787
    data_dir: Path = Path(os.getenv("SPECFORGE_DATA_DIR", REPO_ROOT / ".specforge"))
    mode: str = os.getenv("SPECFORGE_MODE", "real-cli")
    backend_cors_origin: str = os.getenv("SPECFORGE_CORS_ORIGIN", "http://127.0.0.1:5178")
    ui_driver_force: str = os.getenv("SPECFORGE_UI_DRIVER_FORCE", "auto")
    playwright_browser: str = os.getenv("SPECFORGE_PLAYWRIGHT_BROWSER", "chromium")
    cli_timeout_seconds: int = int(os.getenv("SPECFORGE_CLI_TIMEOUT_SECONDS", "7200") or "7200")
    cli_idle_timeout_seconds: int = int(os.getenv("SPECFORGE_CLI_IDLE_TIMEOUT_SECONDS", "900") or "900")
    cli_result_max_chars: int = int(os.getenv("SPECFORGE_CLI_RESULT_MAX_CHARS", str(512 * 1024)) or str(512 * 1024))
    job_queue_max_size: int = int(os.getenv("SPECFORGE_JOB_QUEUE_MAX_SIZE", "256") or "256")
    event_queue_max_size: int = int(os.getenv("SPECFORGE_EVENT_QUEUE_MAX_SIZE", "256") or "256")
    sqlite_timeout_seconds: float = float(os.getenv("SPECFORGE_SQLITE_TIMEOUT_SECONDS", "30") or "30")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "specforge.sqlite3"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def langgraph_db_path(self) -> Path:
        return self.data_dir / "langgraph_checkpoints.sqlite3"

    @property
    def active_cli_registry_path(self) -> Path:
        return self.data_dir / "active_cli.json"


settings = Settings()
