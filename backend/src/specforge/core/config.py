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

    @property
    def db_path(self) -> Path:
        return self.data_dir / "specforge.sqlite3"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def langgraph_db_path(self) -> Path:
        return self.data_dir / "langgraph_checkpoints.sqlite3"


settings = Settings()
