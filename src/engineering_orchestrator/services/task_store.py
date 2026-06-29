from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engineering_orchestrator.models import (
    AgentRun,
    AgentStep,
    Approval,
    ApprovalStatus,
    EvaluationResult,
    Task,
    TaskArtifact,
    TaskEvent,
    TaskJob,
    TaskStatus,
)


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

                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  task_id TEXT NOT NULL,
                  action TEXT NOT NULL,
                  status TEXT NOT NULL,
                  error TEXT,
                  created_at TEXT NOT NULL,
                  started_at TEXT,
                  finished_at TEXT,
                  FOREIGN KEY(task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                  id TEXT PRIMARY KEY,
                  task_id TEXT NOT NULL,
                  run_type TEXT NOT NULL,
                  status TEXT NOT NULL,
                  executor TEXT,
                  model TEXT,
                  started_at TEXT NOT NULL,
                  finished_at TEXT,
                  iteration_count INTEGER NOT NULL DEFAULT 0,
                  stop_reason TEXT,
                  FOREIGN KEY(task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS agent_steps (
                  id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL,
                  step_index INTEGER NOT NULL,
                  step_type TEXT NOT NULL,
                  status TEXT NOT NULL,
                  input_summary TEXT,
                  output_summary TEXT,
                  artifact_ids_json TEXT NOT NULL,
                  started_at TEXT NOT NULL,
                  finished_at TEXT,
                  error TEXT,
                  FOREIGN KEY(run_id) REFERENCES agent_runs(id)
                );

                CREATE TABLE IF NOT EXISTS evaluation_results (
                  id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL,
                  task_id TEXT NOT NULL,
                  passed INTEGER NOT NULL,
                  score REAL,
                  status TEXT NOT NULL,
                  findings_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(run_id) REFERENCES agent_runs(id),
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

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        workflow_id: str | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        tasks, _total = self.list_tasks_page(status, project_id, workflow_id, q, limit, offset)
        return tasks

    def list_tasks_page(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        workflow_id: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Task], int]:
        sql = "SELECT * FROM tasks"
        count_sql = "SELECT COUNT(*) AS count FROM tasks"
        params: list[Any] = []
        clauses: list[str] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if workflow_id is not None:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        if q:
            clauses.append("(id LIKE ? OR user_message LIKE ? OR artifacts_dir LIKE ?)")
            pattern = f"%{q}%"
            params.extend([pattern, pattern, pattern])
        if clauses:
            where = " WHERE " + " AND ".join(clauses)
            sql += where
            count_sql += where
        sql += " ORDER BY updated_at DESC, id DESC"
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        if limit > 0:
            sql += " LIMIT ? OFFSET ?"
            page_params = [*params, limit, offset]
        else:
            page_params = params
        with self.connect() as conn:
            rows = conn.execute(sql, page_params).fetchall()
            total_row = conn.execute(count_sql, params).fetchone()
        return [self._row_to_task(row) for row in rows], int(total_row["count"])

    def update_task(self, task: Task) -> None:
        if task.status not in {"closed", "cancelled"}:
            task.closed_at = None
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
            if artifact.version is None:
                existing = conn.execute(
                    """
                    SELECT * FROM artifacts
                    WHERE task_id = ? AND kind = ? AND version IS NULL
                    ORDER BY created_at, id
                    """,
                    (artifact.task_id, artifact.kind),
                ).fetchall()
                if existing:
                    first = self._row_to_artifact(existing[0])
                    artifact.id = first.id
                    artifact.created_at = first.created_at
                    duplicate_ids = [row["id"] for row in existing[1:]]
                    if duplicate_ids:
                        conn.executemany("DELETE FROM artifacts WHERE id = ?", [(artifact_id,) for artifact_id in duplicate_ids])

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

    def upsert_artifact_by_kind(self, task_id: str, artifact: TaskArtifact) -> None:
        artifact.task_id = task_id
        artifact.version = None
        self.add_artifact(artifact)

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

    def get_artifact_by_id(self, task_id: str, artifact_id: str) -> TaskArtifact | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE task_id = ? AND id = ?",
                (task_id, artifact_id),
            ).fetchone()
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

    def get_current_approval_gate(self, task_id: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT gate FROM approvals
                WHERE task_id = ? AND status = 'pending'
                ORDER BY created_at, id
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return str(row["gate"]) if row else None

    def cancel_task(self, task_id: str, comment: str | None = None) -> Task:
        task = self.get_task(task_id)
        if task.status in {"closed", "cancelled"}:
            raise ValueError(f"Task cannot be cancelled from status: {task.status}")

        task.status = "cancelled"
        task.closed_at = utc_now()
        self.update_task(task)

        now = utc_now().isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE approvals
                SET status = 'cancelled', user_comment = COALESCE(?, user_comment), resolved_at = ?
                WHERE task_id = ? AND status = 'pending'
                """,
                (comment, now, task_id),
            )
        return self.get_task(task_id)

    def add_event(self, task_id: str, event_type: str, payload: dict[str, Any] | None = None) -> TaskEvent:
        event = TaskEvent(id=new_id("event"), task_id=task_id, event_type=event_type, payload=payload or {}, created_at=utc_now())
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO task_events (id, task_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (event.id, event.task_id, event.event_type, _json(event.payload), event.created_at.isoformat()),
            )
        return event

    def create_job(self, task_id: str, action: str) -> TaskJob:
        job = TaskJob(
            id=new_id("job"),
            task_id=task_id,
            action=action,
            status="queued",
            created_at=utc_now(),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, task_id, action, status, error, created_at, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.task_id,
                    job.action,
                    job.status,
                    job.error,
                    job.created_at.isoformat(),
                    None,
                    None,
                ),
            )
        return job

    def start_job(self, job_id: str) -> TaskJob:
        started_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
                (started_at.isoformat(), job_id),
            )
        return self.get_job(job_id)

    def finish_job(self, job_id: str, status: str, error: str | None = None) -> TaskJob:
        finished_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
                (status, error, finished_at.isoformat(), job_id),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> TaskJob:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Job not found: {job_id}")
        return self._row_to_job(row)

    def list_jobs(self, task_id: str) -> list[TaskJob]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE task_id = ? ORDER BY created_at, id",
                (task_id,),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def list_events(self, task_id: str) -> list[TaskEvent]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at, id",
                (task_id,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def create_run(
        self,
        task_id: str,
        run_type: str,
        status: str = "running",
        executor: str | None = None,
        model: str | None = None,
    ) -> AgentRun:
        run = AgentRun(
            id=new_id("run"),
            task_id=task_id,
            run_type=run_type,
            status=status,
            executor=executor,
            model=model,
            started_at=utc_now(),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                  id, task_id, run_type, status, executor, model, started_at,
                  finished_at, iteration_count, stop_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.task_id,
                    run.run_type,
                    run.status,
                    run.executor,
                    run.model,
                    run.started_at.isoformat(),
                    None,
                    run.iteration_count,
                    run.stop_reason,
                ),
            )
        return run

    def finish_run(
        self,
        run_id: str,
        status: str,
        iteration_count: int | None = None,
        stop_reason: str | None = None,
    ) -> AgentRun:
        run = self.get_run(run_id)
        run.status = status
        run.finished_at = utc_now()
        if iteration_count is not None:
            run.iteration_count = iteration_count
        run.stop_reason = stop_reason
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE agent_runs
                SET status = ?, finished_at = ?, iteration_count = ?, stop_reason = ?
                WHERE id = ?
                """,
                (run.status, run.finished_at.isoformat(), run.iteration_count, run.stop_reason, run.id),
            )
        return run

    def get_run(self, run_id: str) -> AgentRun:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Run not found: {run_id}")
        return self._row_to_run(row)

    def list_runs(self, task_id: str) -> list[AgentRun]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE task_id = ? ORDER BY started_at, id",
                (task_id,),
            ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def add_step(
        self,
        run_id: str,
        step_index: int,
        step_type: str,
        status: str,
        input_summary: str | None = None,
        output_summary: str | None = None,
        artifact_ids: list[str] | None = None,
        error: str | None = None,
        finished: bool = True,
    ) -> AgentStep:
        now = utc_now()
        step = AgentStep(
            id=new_id("step"),
            run_id=run_id,
            step_index=step_index,
            step_type=step_type,
            status=status,
            input_summary=input_summary,
            output_summary=output_summary,
            artifact_ids=artifact_ids or [],
            started_at=now,
            finished_at=now if finished else None,
            error=error,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_steps (
                  id, run_id, step_index, step_type, status, input_summary,
                  output_summary, artifact_ids_json, started_at, finished_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step.id,
                    step.run_id,
                    step.step_index,
                    step.step_type,
                    step.status,
                    step.input_summary,
                    step.output_summary,
                    _json(step.artifact_ids),
                    step.started_at.isoformat(),
                    step.finished_at.isoformat() if step.finished_at else None,
                    step.error,
                ),
            )
        return step

    def finish_step(
        self,
        step_id: str,
        status: str,
        output_summary: str | None = None,
        artifact_ids: list[str] | None = None,
        error: str | None = None,
    ) -> AgentStep:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM agent_steps WHERE id = ?", (step_id,)).fetchone()
        if row is None:
            raise KeyError(f"Step not found: {step_id}")
        step = self._row_to_step(row)
        step.status = status
        step.output_summary = output_summary
        if artifact_ids is not None:
            step.artifact_ids = artifact_ids
        step.error = error
        step.finished_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE agent_steps
                SET status = ?, output_summary = ?, artifact_ids_json = ?, finished_at = ?, error = ?
                WHERE id = ?
                """,
                (
                    step.status,
                    step.output_summary,
                    _json(step.artifact_ids),
                    step.finished_at.isoformat(),
                    step.error,
                    step.id,
                ),
            )
        return step

    def list_steps(self, run_id: str) -> list[AgentStep]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_steps WHERE run_id = ? ORDER BY step_index, id",
                (run_id,),
            ).fetchall()
        return [self._row_to_step(row) for row in rows]

    def add_evaluation(
        self,
        run_id: str,
        task_id: str,
        passed: bool,
        status: str,
        findings: list[dict[str, Any]] | None = None,
        score: float | None = None,
    ) -> EvaluationResult:
        evaluation = EvaluationResult(
            id=new_id("eval"),
            run_id=run_id,
            task_id=task_id,
            passed=passed,
            score=score,
            status=status,
            findings=findings or [],
            created_at=utc_now(),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_results (
                  id, run_id, task_id, passed, score, status, findings_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation.id,
                    evaluation.run_id,
                    evaluation.task_id,
                    1 if evaluation.passed else 0,
                    evaluation.score,
                    evaluation.status,
                    _json(evaluation.findings),
                    evaluation.created_at.isoformat(),
                ),
            )
        return evaluation

    def list_evaluations(self, task_id: str) -> list[EvaluationResult]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evaluation_results WHERE task_id = ? ORDER BY created_at, id",
                (task_id,),
            ).fetchall()
        return [self._row_to_evaluation(row) for row in rows]

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

    def _row_to_job(self, row: sqlite3.Row) -> TaskJob:
        return TaskJob(
            id=row["id"],
            task_id=row["task_id"],
            action=row["action"],
            status=row["status"],
            error=row["error"],
            created_at=_dt(row["created_at"]),
            started_at=_dt(row["started_at"]),
            finished_at=_dt(row["finished_at"]),
        )

    def _row_to_run(self, row: sqlite3.Row) -> AgentRun:
        return AgentRun(
            id=row["id"],
            task_id=row["task_id"],
            run_type=row["run_type"],
            status=row["status"],
            executor=row["executor"],
            model=row["model"],
            started_at=_dt(row["started_at"]),
            finished_at=_dt(row["finished_at"]),
            iteration_count=row["iteration_count"],
            stop_reason=row["stop_reason"],
        )

    def _row_to_step(self, row: sqlite3.Row) -> AgentStep:
        return AgentStep(
            id=row["id"],
            run_id=row["run_id"],
            step_index=row["step_index"],
            step_type=row["step_type"],
            status=row["status"],
            input_summary=row["input_summary"],
            output_summary=row["output_summary"],
            artifact_ids=json.loads(row["artifact_ids_json"]),
            started_at=_dt(row["started_at"]),
            finished_at=_dt(row["finished_at"]),
            error=row["error"],
        )

    def _row_to_evaluation(self, row: sqlite3.Row) -> EvaluationResult:
        return EvaluationResult(
            id=row["id"],
            run_id=row["run_id"],
            task_id=row["task_id"],
            passed=bool(row["passed"]),
            score=row["score"],
            status=row["status"],
            findings=json.loads(row["findings_json"]),
            created_at=_dt(row["created_at"]),
        )
