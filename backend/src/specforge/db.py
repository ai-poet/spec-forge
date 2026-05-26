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
                    project_name TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_node TEXT,
                    test_command TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
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
                    finished_at TEXT
                );
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(iterations)").fetchall()
            }
            if "project_id" not in columns:
                conn.execute("ALTER TABLE iterations ADD COLUMN project_id TEXT")

    def create_project(self, *, name: str, description: Optional[str] = None) -> str:
        now = iso(utcnow())
        project_id = f"proj_{uuid4().hex[:8]}"
        with self.connect() as conn:
            existing = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
            if existing is not None:
                return existing["id"]
            conn.execute(
                """
                INSERT INTO projects (id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, name, description, now, now),
            )
        return project_id

    def list_projects(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC, created_at DESC").fetchall()
        return list(rows)

    def get_project_row(self, project_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()

    def create_iteration(
        self,
        *,
        project_name: str,
        goal: str,
        mode: str,
        test_command: Optional[str],
        project_id: Optional[str] = None,
    ) -> str:
        iteration_id = f"iter_{uuid4().hex[:8]}"
        now = iso(utcnow())
        resolved_project_id = project_id or self.create_project(name=project_name)
        project_row = self.get_project_row(resolved_project_id)
        resolved_project_name = project_row["name"] if project_row is not None else project_name
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO iterations (id, project_id, project_name, goal, mode, status, current_node, test_command, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (iteration_id, resolved_project_id, resolved_project_name, goal, mode, "created", None, test_command, now, now),
            )
            conn.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, resolved_project_id),
            )
        return iteration_id

    def update_iteration(
        self,
        iteration_id: str,
        *,
        status: Optional[str] = None,
        current_node: Any = _UNSET,
        test_command: Optional[str] = None,
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
        fields.append("updated_at = ?")
        values.append(iso(utcnow()))
        values.append(iteration_id)
        sql = f"UPDATE iterations SET {', '.join(fields)} WHERE id = ?"
        with self.connect() as conn:
            conn.execute(sql, values)

    def get_iteration_row(self, iteration_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM iterations WHERE id = ?", (iteration_id,)).fetchone()

    def list_iterations(self, project_id: Optional[str] = None) -> list[sqlite3.Row]:
        with self.connect() as conn:
            if project_id:
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
        finished_at: Optional[str] = None,
    ) -> str:
        run_id = f"run_{uuid4().hex[:8]}"
        now = iso(utcnow())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (id, iteration_id, node, status, command, stdout, stderr, exit_code, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, iteration_id, node, status, command, stdout, stderr, exit_code, now, finished_at),
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
