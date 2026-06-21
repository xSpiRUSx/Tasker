from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engineering_orchestrator.models import Approval, ApprovalStatus, Task, TaskArtifact, TaskEvent, TaskStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class TaskStore:
    def __init__(self, sqlite_path: str | Path):
        self.sqlite_path = Path(sqlite_path)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  user_message TEXT NOT NULL,
                  source TEXT,
                  user_id TEXT,
                  project_id TEXT,
                  project_name TEXT,
                  project_path TEXT,
                  workflow_id TEXT,
                  workflow_name TEXT,
                  risk_level TEXT,
                  route_decision_json TEXT,
                  branch_name TEXT,
                  worktree_path TEXT,
                  artifacts_dir TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  closed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                  id TEXT PRIMARY KEY,
                  task_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  version INTEGER,
                  title TEXT NOT NULL,
                  relative_path TEXT NOT NULL,
                  content_type TEXT NOT NULL,
                  content_hash TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  approved_at TEXT,
                  FOREIGN KEY(task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS approvals (
                  id TEXT PRIMARY KEY,
                  task_id TEXT NOT NULL,
                  gate TEXT NOT NULL,
                  status TEXT NOT NULL,
                  artifact_ids_json TEXT NOT NULL,
                  requested_payload_json TEXT NOT NULL,
                  user_comment TEXT,
                  created_at TEXT NOT NULL,
                  resolved_at TEXT,
                  FOREIGN KEY(task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS task_events (
                  id TEXT PRIMARY KEY,
                  task_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                """
            )

    def next_task_id(self, prefix: str) -> str:
        year = utc_now().year
        pattern = f"{prefix}-{year}-%"
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM tasks WHERE id LIKE ?", (pattern,)).fetchone()
        return f"{prefix}-{year}-{int(row['count']) + 1:05d}"

    def create_task(self, user_message: str, source: str | None = None, user_id: str | None = None, prefix: str = "ENG") -> Task:
        now = utc_now()
        task = Task(
            id=self.next_task_id(prefix),
            status="created",
            user_message=user_message,
            source=source,
            user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                  id, status, user_message, source, user_id, project_id, project_name,
                  project_path, workflow_id, workflow_name, risk_level, route_decision_json,
                  branch_name, worktree_path, artifacts_dir, created_at, updated_at, closed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._task_values(task),
            )
        return task

    def get_task(self, task_id: str) -> Task:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Task not found: {task_id}")
        return self._row_to_task(row)

    def update_task(self, task: Task) -> None:
        task.updated_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks SET
                  status = ?, user_message = ?, source = ?, user_id = ?, project_id = ?,
                  project_name = ?, project_path = ?, workflow_id = ?, workflow_name = ?,
                  risk_level = ?, route_decision_json = ?, branch_name = ?, worktree_path = ?,
                  artifacts_dir = ?, created_at = ?, updated_at = ?, closed_at = ?
                WHERE id = ?
                """,
                (
                    task.status,
                    task.user_message,
                    task.source,
                    task.user_id,
                    task.project_id,
                    task.project_name,
                    task.project_path,
                    task.workflow_id,
                    task.workflow_name,
                    task.risk_level,
                    _json(task.route_decision) if task.route_decision is not None else None,
                    task.branch_name,
                    task.worktree_path,
                    task.artifacts_dir,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    task.closed_at.isoformat() if task.closed_at else None,
                    task.id,
                ),
            )

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        task = self.get_task(task_id)
        task.status = status
        if status == "closed":
            task.closed_at = utc_now()
        self.update_task(task)

    def add_artifact(self, artifact: TaskArtifact) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO artifacts (
                  id, task_id, kind, version, title, relative_path, content_type,
                  content_hash, created_at, updated_at, approved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.task_id,
                    artifact.kind,
                    artifact.version,
                    artifact.title,
                    artifact.relative_path,
                    artifact.content_type,
                    artifact.content_hash,
                    artifact.created_at.isoformat(),
                    artifact.updated_at.isoformat(),
                    artifact.approved_at.isoformat() if artifact.approved_at else None,
                ),
            )

    def update_artifact(self, artifact: TaskArtifact) -> None:
        artifact.updated_at = utc_now()
        self.add_artifact(artifact)

    def list_artifacts(self, task_id: str) -> list[TaskArtifact]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE task_id = ? ORDER BY relative_path, version",
                (task_id,),
            ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    def get_artifact(self, task_id: str, kind: str, version: int | None = None) -> TaskArtifact | None:
        sql = "SELECT * FROM artifacts WHERE task_id = ? AND kind = ?"
        params: list[Any] = [task_id, kind]
        if version is not None:
            sql += " AND version = ?"
            params.append(version)
        sql += " ORDER BY COALESCE(version, 0) DESC LIMIT 1"
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._row_to_artifact(row) if row else None

    def create_approval(
        self,
        task_id: str,
        gate: str,
        artifact_ids: list[str],
        requested_payload: dict[str, Any] | None = None,
    ) -> Approval:
        approval = Approval(
            id=new_id("approval"),
            task_id=task_id,
            gate=gate,
            status="pending",
            artifact_ids=artifact_ids,
            requested_payload=requested_payload or {},
            created_at=utc_now(),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (
                  id, task_id, gate, status, artifact_ids_json, requested_payload_json,
                  user_comment, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.id,
                    approval.task_id,
                    approval.gate,
                    approval.status,
                    _json(approval.artifact_ids),
                    _json(approval.requested_payload),
                    approval.user_comment,
                    approval.created_at.isoformat(),
                    None,
                ),
            )
        return approval

    def resolve_approval(self, approval_id: str, status: ApprovalStatus, comment: str | None = None) -> Approval:
        resolved_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE approvals SET status = ?, user_comment = ?, resolved_at = ? WHERE id = ?",
                (status, comment, resolved_at.isoformat(), approval_id),
            )
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError(f"Approval not found: {approval_id}")
        return self._row_to_approval(row)

    def get_pending_approval(self, task_id: str, gate: str) -> Approval | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM approvals
                WHERE task_id = ? AND gate = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
                """,
                (task_id, gate),
            ).fetchone()
        return self._row_to_approval(row) if row else None

    def list_approvals(self, task_id: str) -> list[Approval]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM approvals
                WHERE task_id = ?
                ORDER BY created_at, id
                """,
                (task_id,),
            ).fetchall()
        return [self._row_to_approval(row) for row in rows]

    def add_event(self, task_id: str, event_type: str, payload: dict[str, Any] | None = None) -> TaskEvent:
        event = TaskEvent(id=new_id("event"), task_id=task_id, event_type=event_type, payload=payload or {}, created_at=utc_now())
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO task_events (id, task_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (event.id, event.task_id, event.event_type, _json(event.payload), event.created_at.isoformat()),
            )
        return event

    def list_events(self, task_id: str) -> list[TaskEvent]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at, id",
                (task_id,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _task_values(self, task: Task) -> tuple[Any, ...]:
        return (
            task.id,
            task.status,
            task.user_message,
            task.source,
            task.user_id,
            task.project_id,
            task.project_name,
            task.project_path,
            task.workflow_id,
            task.workflow_name,
            task.risk_level,
            _json(task.route_decision) if task.route_decision is not None else None,
            task.branch_name,
            task.worktree_path,
            task.artifacts_dir,
            task.created_at.isoformat(),
            task.updated_at.isoformat(),
            task.closed_at.isoformat() if task.closed_at else None,
        )

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        route_decision = json.loads(row["route_decision_json"]) if row["route_decision_json"] else None
        return Task(
            id=row["id"],
            status=row["status"],
            user_message=row["user_message"],
            source=row["source"],
            user_id=row["user_id"],
            project_id=row["project_id"],
            project_name=row["project_name"],
            project_path=row["project_path"],
            workflow_id=row["workflow_id"],
            workflow_name=row["workflow_name"],
            risk_level=row["risk_level"],
            route_decision=route_decision,
            branch_name=row["branch_name"],
            worktree_path=row["worktree_path"],
            artifacts_dir=row["artifacts_dir"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            closed_at=_dt(row["closed_at"]),
        )

    def _row_to_artifact(self, row: sqlite3.Row) -> TaskArtifact:
        return TaskArtifact(
            id=row["id"],
            task_id=row["task_id"],
            kind=row["kind"],
            version=row["version"],
            title=row["title"],
            relative_path=row["relative_path"],
            content_type=row["content_type"],
            content_hash=row["content_hash"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            approved_at=_dt(row["approved_at"]),
        )

    def _row_to_approval(self, row: sqlite3.Row) -> Approval:
        return Approval(
            id=row["id"],
            task_id=row["task_id"],
            gate=row["gate"],
            status=row["status"],
            artifact_ids=json.loads(row["artifact_ids_json"]),
            requested_payload=json.loads(row["requested_payload_json"]),
            user_comment=row["user_comment"],
            created_at=_dt(row["created_at"]),
            resolved_at=_dt(row["resolved_at"]),
        )

    def _row_to_event(self, row: sqlite3.Row) -> TaskEvent:
        return TaskEvent(
            id=row["id"],
            task_id=row["task_id"],
            event_type=row["event_type"],
            payload=json.loads(row["payload_json"]),
            created_at=_dt(row["created_at"]),
        )
