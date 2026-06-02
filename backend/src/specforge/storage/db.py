from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


_UNSET = object()


@dataclass
class Database:
    path: Path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS iterations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    epic_id TEXT,
                    project_name TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_node TEXT,
                    test_command TEXT,
                    retry_counts TEXT NOT NULL DEFAULT '{}',
                    test_integrity_baseline TEXT NOT NULL DEFAULT '{}',
                    planning_integrity_baseline TEXT NOT NULL DEFAULT '{}',
                    planning_cli_session_id TEXT,
                    planning_cli_session_started INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    default_mode TEXT NOT NULL DEFAULT 'real-cli',
                    default_test_command TEXT,
                    planner_model TEXT,
                    coder_model TEXT,
                    tester_model TEXT,
                    max_coder_tester_retries INTEGER NOT NULL DEFAULT 5,
                    max_clarifications INTEGER NOT NULL DEFAULT 3,
                    max_verify_rejects INTEGER NOT NULL DEFAULT 2,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS epics (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    acceptance_criteria TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    iteration_id TEXT NOT NULL REFERENCES iterations(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    iteration_id TEXT NOT NULL REFERENCES iterations(id) ON DELETE CASCADE,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    iteration_id TEXT NOT NULL REFERENCES iterations(id) ON DELETE CASCADE,
                    node TEXT NOT NULL,
                    status TEXT NOT NULL,
                    command TEXT NOT NULL,
                    stdout TEXT NOT NULL,
                    stderr TEXT NOT NULL,
                    exit_code INTEGER,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    stdout_bytes INTEGER NOT NULL DEFAULT 0,
                    stderr_bytes INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            iteration_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(iterations)").fetchall()
            }
            if "project_id" not in iteration_columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN project_id TEXT")
            if "epic_id" not in iteration_columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN epic_id TEXT")
            if "retry_counts" not in iteration_columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN retry_counts TEXT NOT NULL DEFAULT '{}'")
            if "test_integrity_baseline" not in iteration_columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN test_integrity_baseline TEXT NOT NULL DEFAULT '{}'")
            if "planning_integrity_baseline" not in iteration_columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN planning_integrity_baseline TEXT NOT NULL DEFAULT '{}'")
            if "last_error" not in iteration_columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN last_error TEXT")
            if "stopped_at_node" not in iteration_columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN stopped_at_node TEXT")
            if "docs_slug" not in iteration_columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN docs_slug TEXT")
            if "build_command" not in iteration_columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN build_command TEXT")
            if "planning_cli_session_id" not in iteration_columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN planning_cli_session_id TEXT")
            if "planning_cli_session_started" not in iteration_columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN planning_cli_session_started INTEGER NOT NULL DEFAULT 0")

            project_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(projects)").fetchall()
            }
            project_defaults = {
                "default_mode": "TEXT NOT NULL DEFAULT 'real-cli'",
                "default_test_command": "TEXT",
                "planner_model": "TEXT",
                "coder_model": "TEXT",
                "tester_model": "TEXT",
                "max_coder_tester_retries": "INTEGER NOT NULL DEFAULT 5",
                "max_clarifications": "INTEGER NOT NULL DEFAULT 3",
                "max_verify_rejects": "INTEGER NOT NULL DEFAULT 2",
                "default_build_command": "TEXT",
                "max_tester_self_retries": "INTEGER NOT NULL DEFAULT 3",
                "max_discovery_rounds": "INTEGER NOT NULL DEFAULT 8",
            }
            for column, definition in project_defaults.items():
                if column not in project_columns:
                    conn.execute(f"ALTER TABLE projects ADD COLUMN {column} {definition}")
            if "root_path" not in project_columns:
                conn.execute("ALTER TABLE projects ADD COLUMN root_path TEXT")
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_root_path ON projects(root_path) WHERE root_path IS NOT NULL")
            if "cli_bindings" not in project_columns:
                conn.execute("ALTER TABLE projects ADD COLUMN cli_bindings TEXT")
            run_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(runs)").fetchall()
            }
            if "duration_ms" not in run_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN duration_ms INTEGER")
            if "stdout_bytes" not in run_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN stdout_bytes INTEGER NOT NULL DEFAULT 0")
                conn.execute("UPDATE runs SET stdout_bytes = length(CAST(stdout AS BLOB)) WHERE stdout_bytes = 0 AND stdout != ''")
            if "stderr_bytes" not in run_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN stderr_bytes INTEGER NOT NULL DEFAULT 0")
                conn.execute("UPDATE runs SET stderr_bytes = length(CAST(stderr AS BLOB)) WHERE stderr_bytes = 0 AND stderr != ''")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_iteration_created ON documents(iteration_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_iteration_created ON events(iteration_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_iteration_started ON runs(iteration_id, started_at)")

    def get_project_by_root_path(self, root_path: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM projects WHERE root_path = ?", (root_path,)).fetchone()

    def create_project(
        self,
        *,
        root_path: str,
        create_if_missing: bool = False,
        name: Optional[str] = None,
        description: Optional[str] = None,
        default_mode: str = "real-cli",
        default_test_command: Optional[str] = None,
        default_build_command: Optional[str] = None,
        max_coder_tester_retries: int = 5,
        max_clarifications: int = 3,
        max_verify_rejects: int = 2,
        max_tester_self_retries: int = 3,
        max_discovery_rounds: int = 8,
    ) -> str:
        from ..documents.project_paths import prepare_project_root

        resolved = prepare_project_root(root_path, create_if_missing)
        resolved_str = str(resolved)
        display_name = name or resolved.name
        now = iso(utcnow())
        project_id = f"proj_{uuid4().hex[:8]}"
        with self.connect() as conn:
            existing_root = conn.execute("SELECT id FROM projects WHERE root_path = ?", (resolved_str,)).fetchone()
            if existing_root is not None:
                raise ValueError(f"project already registered for root_path: {resolved_str}")
            existing_name = conn.execute("SELECT id FROM projects WHERE name = ?", (display_name,)).fetchone()
            if existing_name is not None:
                raise ValueError(f"project name already exists: {display_name}")
            conn.execute(
                """
                INSERT INTO projects (
                    id, name, root_path, description, default_mode, default_test_command,
                    default_build_command, planner_model, coder_model, tester_model,
                    max_coder_tester_retries, max_clarifications, max_verify_rejects,
                    max_tester_self_retries, max_discovery_rounds, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    display_name,
                    resolved_str,
                    description,
                    default_mode,
                    default_test_command,
                    default_build_command,
                    None,
                    None,
                    None,
                    max_coder_tester_retries,
                    max_clarifications,
                    max_verify_rejects,
                    max_tester_self_retries,
                    max_discovery_rounds,
                    now,
                    now,
                ),
            )
        return project_id

    def update_project(self, project_id: str, **fields: Any) -> None:
        allowed = {
            "name",
            "description",
            "root_path",
            "default_mode",
            "default_test_command",
            "default_build_command",
            "cli_bindings",
            "max_coder_tester_retries",
            "max_clarifications",
            "max_verify_rejects",
            "max_tester_self_retries",
            "max_discovery_rounds",
        }
        updates = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed or value is _UNSET:
                continue
            updates.append(f"{key} = ?")
            values.append(value)
        if not updates:
            return
        updates.append("updated_at = ?")
        values.append(iso(utcnow()))
        values.append(project_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = ?", values)

    def list_projects(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC, created_at DESC").fetchall()
        return list(rows)

    def get_project_row(self, project_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()

    def delete_project(self, project_id: str) -> bool:
        with self.connect() as conn:
            exists = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if exists is None:
                return False
            conn.execute("DELETE FROM iterations WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM epics WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return True

    def delete_epic(self, epic_id: str) -> bool:
        with self.connect() as conn:
            exists = conn.execute("SELECT id FROM epics WHERE id = ?", (epic_id,)).fetchone()
            if exists is None:
                return False
            conn.execute("DELETE FROM iterations WHERE epic_id = ?", (epic_id,))
            conn.execute("DELETE FROM epics WHERE id = ?", (epic_id,))
        return True

    def delete_iteration(self, iteration_id: str) -> bool:
        with self.connect() as conn:
            exists = conn.execute("SELECT id FROM iterations WHERE id = ?", (iteration_id,)).fetchone()
            if exists is None:
                return False
            conn.execute("DELETE FROM iterations WHERE id = ?", (iteration_id,))
        return True

    def create_epic(
        self,
        *,
        project_id: str,
        title: str,
        description: str = "",
        acceptance_criteria: str = "",
    ) -> str:
        now = iso(utcnow())
        epic_id = f"epic_{uuid4().hex[:8]}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO epics (id, project_id, title, description, acceptance_criteria, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (epic_id, project_id, title, description, acceptance_criteria, "draft", now, now),
            )
            conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
        return epic_id

    def update_epic_status(self, epic_id: str) -> None:
        iterations = self.list_iterations(epic_id=epic_id)
        if not iterations:
            status = "draft"
        elif any(row["status"] in {"blocked", "blocked_user", "failed", "stopped"} for row in iterations):
            status = "blocked"
        elif all(row["status"] == "delivered" for row in iterations):
            status = "delivered"
        else:
            status = "active"
        self.update_epic(epic_id, status=status)

    def update_epic(self, epic_id: str, **fields: Any) -> None:
        allowed = {"title", "description", "acceptance_criteria", "status"}
        updates = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed or value is _UNSET:
                continue
            updates.append(f"{key} = ?")
            values.append(value)
        if not updates:
            return
        updates.append("updated_at = ?")
        values.append(iso(utcnow()))
        values.append(epic_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE epics SET {', '.join(updates)} WHERE id = ?", values)

    def get_epic_row(self, epic_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()

    def list_epics(self, project_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM epics WHERE project_id = ? ORDER BY updated_at DESC, created_at DESC",
                (project_id,),
            ).fetchall()
        return list(rows)

    def create_iteration(
        self,
        *,
        project_name: str,
        goal: str,
        mode: Optional[str],
        test_command: Optional[str],
        build_command: Optional[str] = None,
        project_id: Optional[str] = None,
        epic_id: Optional[str] = None,
    ) -> str:
        iteration_id = f"iter_{uuid4().hex[:8]}"
        now = iso(utcnow())
        if project_id:
            resolved_project_id = project_id
        else:
            from ..core.config import settings

            legacy_root = str((settings.projects_dir / f"legacy_{project_name}").resolve())
            resolved_project_id = self.create_project(
                root_path=legacy_root,
                create_if_missing=True,
                name=project_name,
            )
        project_row = self.get_project_row(resolved_project_id)
        resolved_project_name = project_row["name"] if project_row is not None else project_name
        resolved_mode = mode or (project_row["default_mode"] if project_row is not None else "real-cli")
        resolved_test_command = test_command
        if resolved_test_command is None and project_row is not None:
            resolved_test_command = project_row["default_test_command"]
        resolved_build_command = build_command
        if resolved_build_command is None and project_row is not None and "default_build_command" in project_row.keys():
            resolved_build_command = project_row["default_build_command"]
        with self.connect() as conn:
            sequence = conn.execute(
                "SELECT COUNT(*) FROM iterations WHERE project_id = ?",
                (resolved_project_id,),
            ).fetchone()[0]
            docs_slug = f"iteration_{int(sequence) + 1:03d}"
            conn.execute(
                """
                INSERT INTO iterations (
                    id, project_id, project_name, goal, mode, status, current_node,
                    test_command, build_command, retry_counts, test_integrity_baseline,
                    planning_integrity_baseline, last_error, epic_id, docs_slug, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iteration_id,
                    resolved_project_id,
                    resolved_project_name,
                    goal,
                    resolved_mode,
                    "created",
                    None,
                    resolved_test_command,
                    resolved_build_command,
                    "{}",
                    "{}",
                    "{}",
                    None,
                    epic_id,
                    docs_slug,
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, resolved_project_id),
            )
            if epic_id:
                conn.execute(
                    "UPDATE epics SET updated_at = ? WHERE id = ?",
                    (now, epic_id),
                )
        return iteration_id

    def update_iteration(
        self,
        iteration_id: str,
        *,
        status: Optional[str] = None,
        current_node: Any = _UNSET,
        test_command: Optional[str] = None,
        build_command: Optional[str] = None,
        retry_counts: Optional[dict[str, int]] = None,
        test_integrity_baseline: Optional[dict[str, Any]] = None,
        planning_integrity_baseline: Optional[dict[str, Any]] = None,
        planning_cli_session_id: Any = _UNSET,
        planning_cli_session_started: Any = _UNSET,
        last_error: Any = _UNSET,
        stopped_at_node: Any = _UNSET,
    ) -> None:
        fields = []
        values: list[Any] = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if current_node is not _UNSET:
            fields.append("current_node = ?")
            values.append(current_node)
        if test_command is not None:
            fields.append("test_command = ?")
            values.append(test_command)
        if build_command is not None:
            fields.append("build_command = ?")
            values.append(build_command)
        if retry_counts is not None:
            fields.append("retry_counts = ?")
            values.append(json.dumps(retry_counts))
        if test_integrity_baseline is not None:
            fields.append("test_integrity_baseline = ?")
            values.append(json.dumps(test_integrity_baseline))
        if planning_integrity_baseline is not None:
            fields.append("planning_integrity_baseline = ?")
            values.append(json.dumps(planning_integrity_baseline))
        if planning_cli_session_id is not _UNSET:
            fields.append("planning_cli_session_id = ?")
            values.append(planning_cli_session_id)
        if planning_cli_session_started is not _UNSET:
            fields.append("planning_cli_session_started = ?")
            values.append(1 if planning_cli_session_started else 0)
        if last_error is not _UNSET:
            fields.append("last_error = ?")
            values.append(last_error)
        if stopped_at_node is not _UNSET:
            fields.append("stopped_at_node = ?")
            values.append(stopped_at_node)
        fields.append("updated_at = ?")
        values.append(iso(utcnow()))
        values.append(iteration_id)
        sql = f"UPDATE iterations SET {', '.join(fields)} WHERE id = ?"
        with self.connect() as conn:
            conn.execute(sql, values)

    def get_iteration_row(self, iteration_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM iterations WHERE id = ?", (iteration_id,)).fetchone()

    def list_iterations(self, project_id: Optional[str] = None, epic_id: Optional[str] = None) -> list[sqlite3.Row]:
        with self.connect() as conn:
            if epic_id:
                rows = conn.execute(
                    "SELECT * FROM iterations WHERE epic_id = ? ORDER BY created_at DESC",
                    (epic_id,),
                ).fetchall()
            elif project_id:
                rows = conn.execute(
                    "SELECT * FROM iterations WHERE project_id = ? ORDER BY created_at DESC",
                    (project_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM iterations ORDER BY created_at DESC").fetchall()
        return list(rows)

    def add_document(self, iteration_id: str, *, name: str, path: str, checksum: str) -> None:
        now = iso(utcnow())
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM documents WHERE iteration_id = ? AND name = ?",
                (iteration_id, name),
            )
            conn.execute(
                """
                INSERT INTO documents (id, iteration_id, name, path, checksum, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (f"doc_{uuid4().hex[:8]}", iteration_id, name, path, checksum, now, now),
            )

    def list_documents(self, iteration_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM documents WHERE iteration_id = ? ORDER BY created_at",
                (iteration_id,),
            ).fetchall()
        return list(rows)

    def add_event(self, iteration_id: str, *, event_type: str, payload: dict[str, Any]) -> sqlite3.Row:
        now = iso(utcnow())
        event_id = f"evt_{uuid4().hex[:8]}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events (id, iteration_id, type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, iteration_id, event_type, json.dumps(payload), now),
            )
            row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        assert row is not None
        return row

    def list_events(self, iteration_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE iteration_id = ? ORDER BY created_at",
                (iteration_id,),
            ).fetchall()
        return list(rows)

    def add_run(
        self,
        iteration_id: str,
        *,
        node: str,
        status: str,
        command: str,
        stdout: str,
        stderr: str,
        exit_code: Optional[int] = None,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        duration_ms: Optional[int] = None,
        stdout_bytes: Optional[int] = None,
        stderr_bytes: Optional[int] = None,
    ) -> str:
        run_id = f"run_{uuid4().hex[:8]}"
        now = started_at or iso(utcnow())
        resolved_stdout_bytes = stdout_bytes if stdout_bytes is not None else len((stdout or "").encode("utf-8"))
        resolved_stderr_bytes = stderr_bytes if stderr_bytes is not None else len((stderr or "").encode("utf-8"))
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, iteration_id, node, status, command, stdout, stderr, exit_code,
                    started_at, finished_at, duration_ms, stdout_bytes, stderr_bytes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    iteration_id,
                    node,
                    status,
                    command,
                    stdout,
                    stderr,
                    exit_code,
                    now,
                    finished_at,
                    duration_ms,
                    resolved_stdout_bytes,
                    resolved_stderr_bytes,
                ),
            )
        return run_id

    def update_run(self, run_id: str, *, status: Optional[str] = None, exit_code: Optional[int] = None, finished_at: Optional[str] = None) -> None:
        fields = []
        values: list[Any] = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if exit_code is not None:
            fields.append("exit_code = ?")
            values.append(exit_code)
        if finished_at is not None:
            fields.append("finished_at = ?")
            values.append(finished_at)
        if not fields:
            return
        values.append(run_id)
        sql = f"UPDATE runs SET {', '.join(fields)} WHERE id = ?"
        with self.connect() as conn:
            conn.execute(sql, values)

    def list_runs(self, iteration_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE iteration_id = ? ORDER BY started_at",
                (iteration_id,),
            ).fetchall()
        return list(rows)

    def iteration_detail_rows(self, iteration_id: str) -> Optional[dict[str, list[sqlite3.Row] | sqlite3.Row]]:
        with self.connect() as conn:
            iteration = conn.execute("SELECT * FROM iterations WHERE id = ?", (iteration_id,)).fetchone()
            if iteration is None:
                return None
            documents = conn.execute(
                "SELECT * FROM documents WHERE iteration_id = ? ORDER BY created_at",
                (iteration_id,),
            ).fetchall()
            events = conn.execute(
                "SELECT * FROM events WHERE iteration_id = ? ORDER BY created_at",
                (iteration_id,),
            ).fetchall()
            runs = conn.execute(
                "SELECT * FROM runs WHERE iteration_id = ? ORDER BY started_at",
                (iteration_id,),
            ).fetchall()
        return {"iteration": iteration, "documents": list(documents), "events": list(events), "runs": list(runs)}
