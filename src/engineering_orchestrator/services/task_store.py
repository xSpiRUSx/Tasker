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
    CorrectionRequest,
    EvaluationResult,
    ModelCallRecord,
    ModelDecisionRecord,
    PromptBuildRecord,
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
                  parent_task_id TEXT,
                  related_task_ids_json TEXT,
                  correction_source TEXT,
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
                  input_json TEXT,
                  result_json TEXT,
                  error TEXT,
                  created_at TEXT NOT NULL,
                  started_at TEXT,
                  finished_at TEXT,
                  FOREIGN KEY(task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS model_decisions (
                  id TEXT PRIMARY KEY,
                  task_id TEXT,
                  run_id TEXT,
                  operation TEXT NOT NULL,
                  profile TEXT NOT NULL,
                  selected_target TEXT NOT NULL,
                  runtime TEXT NOT NULL,
                  model TEXT NOT NULL,
                  reasoning_effort TEXT,
                  reason TEXT,
                  estimated_prompt_chars INTEGER,
                  max_prompt_chars INTEGER,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS model_calls (
                  id TEXT PRIMARY KEY,
                  task_id TEXT,
                  run_id TEXT,
                  operation TEXT NOT NULL,
                  runtime TEXT NOT NULL,
                  provider TEXT,
                  model TEXT NOT NULL,
                  reasoning_effort TEXT,
                  prompt_chars INTEGER,
                  prompt_tokens INTEGER,
                  completion_tokens INTEGER,
                  cached_prompt_tokens INTEGER,
                  reasoning_tokens INTEGER,
                  total_tokens INTEGER,
                  usage_source TEXT,
                  usage_is_estimated INTEGER DEFAULT 0,
                  cost_usd REAL,
                  latency_ms INTEGER,
                  status TEXT,
                  error TEXT,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS prompt_builds (
                  id TEXT PRIMARY KEY,
                  task_id TEXT,
                  run_id TEXT,
                  operation TEXT NOT NULL,
                  total_chars INTEGER NOT NULL,
                  budget_chars INTEGER NOT NULL,
                  included_json TEXT NOT NULL,
                  excluded_json TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifact_summaries (
                  id TEXT PRIMARY KEY,
                  artifact_id TEXT NOT NULL,
                  content_hash TEXT NOT NULL,
                  summary TEXT NOT NULL,
                  model_target TEXT,
                  created_at TEXT NOT NULL
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
                  correction_request_id TEXT,
                  FOREIGN KEY(task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS correction_requests (
                  id TEXT PRIMARY KEY,
                  task_id TEXT NOT NULL,
                  source_gate TEXT NOT NULL,
                  source_approval_id TEXT,
                  source_artifact_id TEXT,
                  user_comment TEXT NOT NULL,
                  mode TEXT NOT NULL,
                  status TEXT NOT NULL,
                  approved_for_execution INTEGER NOT NULL,
                  requires_plan_approval INTEGER NOT NULL,
                  requires_spec_addendum INTEGER NOT NULL,
                  classifier_result_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
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

                CREATE TABLE IF NOT EXISTS routing_rules (
                  id TEXT PRIMARY KEY,
                  rule_type TEXT NOT NULL,
                  pattern_type TEXT NOT NULL,
                  pattern TEXT NOT NULL,
                  language TEXT,
                  target_route_type TEXT NOT NULL,
                  target_workflow_id TEXT,
                  target_task_kind TEXT,
                  target_project_id TEXT,
                  constraints_json TEXT,
                  positive_examples_json TEXT,
                  negative_examples_json TEXT,
                  confidence REAL,
                  priority INTEGER DEFAULT 100,
                  status TEXT NOT NULL,
                  source TEXT NOT NULL,
                  source_task_id TEXT,
                  source_message TEXT,
                  hit_count INTEGER DEFAULT 0,
                  false_positive_count INTEGER DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routing_rule_suggestions (
                  id TEXT PRIMARY KEY,
                  task_id TEXT,
                  message TEXT NOT NULL,
                  classifier_result_json TEXT NOT NULL,
                  suggested_rules_json TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  resolved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS routing_feedback (
                  id TEXT PRIMARY KEY,
                  task_id TEXT,
                  original_route_json TEXT,
                  final_route_json TEXT,
                  user_correction TEXT,
                  accepted INTEGER,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routing_diagnostics (
                  id TEXT PRIMARY KEY,
                  task_id TEXT,
                  message TEXT NOT NULL,
                  deterministic_result_json TEXT,
                  classifier_result_json TEXT,
                  final_result_json TEXT NOT NULL,
                  used_classifier INTEGER NOT NULL,
                  created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "agent_runs", "correction_request_id", "TEXT")
            self._ensure_column(conn, "jobs", "input_json", "TEXT")
            self._ensure_column(conn, "jobs", "result_json", "TEXT")
            self._ensure_column(conn, "tasks", "parent_task_id", "TEXT")
            self._ensure_column(conn, "tasks", "related_task_ids_json", "TEXT")
            self._ensure_column(conn, "tasks", "correction_source", "TEXT")
            self._ensure_column(conn, "model_calls", "cached_prompt_tokens", "INTEGER")
            self._ensure_column(conn, "model_calls", "reasoning_tokens", "INTEGER")
            self._ensure_column(conn, "model_calls", "total_tokens", "INTEGER")
            self._ensure_column(conn, "model_calls", "usage_source", "TEXT")
            self._ensure_column(conn, "model_calls", "usage_is_estimated", "INTEGER DEFAULT 0")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
                  parent_task_id, related_task_ids_json, correction_source,
                  branch_name, worktree_path, artifacts_dir, created_at, updated_at, closed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                  risk_level = ?, route_decision_json = ?, parent_task_id = ?,
                  related_task_ids_json = ?, correction_source = ?, branch_name = ?, worktree_path = ?,
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
                    task.parent_task_id,
                    _json(task.related_task_ids),
                    task.correction_source,
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

    def next_correction_number(self, task_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM correction_requests WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return int(row["count"]) + 1

    def create_correction_request(
        self,
        task_id: str,
        source_gate: str,
        user_comment: str,
        mode: str,
        status: str,
        approved_for_execution: bool,
        requires_plan_approval: bool,
        requires_spec_addendum: bool,
        classifier_result: dict[str, Any],
        source_approval_id: str | None = None,
        source_artifact_id: str | None = None,
    ) -> CorrectionRequest:
        now = utc_now()
        correction = CorrectionRequest(
            id=f"correction-{self.next_correction_number(task_id):03d}",
            task_id=task_id,
            source_gate=source_gate,
            source_approval_id=source_approval_id,
            source_artifact_id=source_artifact_id,
            user_comment=user_comment,
            mode=mode,  # type: ignore[arg-type]
            status=status,
            approved_for_execution=approved_for_execution,
            requires_plan_approval=requires_plan_approval,
            requires_spec_addendum=requires_spec_addendum,
            classifier_result=classifier_result,
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO correction_requests (
                  id, task_id, source_gate, source_approval_id, source_artifact_id,
                  user_comment, mode, status, approved_for_execution,
                  requires_plan_approval, requires_spec_addendum,
                  classifier_result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    correction.id,
                    correction.task_id,
                    correction.source_gate,
                    correction.source_approval_id,
                    correction.source_artifact_id,
                    correction.user_comment,
                    correction.mode,
                    correction.status,
                    1 if correction.approved_for_execution else 0,
                    1 if correction.requires_plan_approval else 0,
                    1 if correction.requires_spec_addendum else 0,
                    _json(correction.classifier_result),
                    correction.created_at.isoformat(),
                    correction.updated_at.isoformat(),
                ),
            )
        return correction

    def update_correction_request_status(self, correction_id: str, status: str) -> CorrectionRequest:
        updated_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE correction_requests SET status = ?, updated_at = ? WHERE id = ?",
                (status, updated_at.isoformat(), correction_id),
            )
            row = conn.execute("SELECT * FROM correction_requests WHERE id = ?", (correction_id,)).fetchone()
        if row is None:
            raise KeyError(f"Correction request not found: {correction_id}")
        return self._row_to_correction_request(row)

    def get_correction_request(self, task_id: str, correction_id: str) -> CorrectionRequest:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM correction_requests WHERE task_id = ? AND id = ?",
                (task_id, correction_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Correction request not found: {correction_id}")
        return self._row_to_correction_request(row)

    def list_correction_requests(self, task_id: str) -> list[CorrectionRequest]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM correction_requests WHERE task_id = ? ORDER BY created_at, id",
                (task_id,),
            ).fetchall()
        return [self._row_to_correction_request(row) for row in rows]

    def create_routing_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        record = {
            "id": rule.get("id") or new_id("rule"),
            "rule_type": rule.get("rule_type") or "intent_pattern",
            "pattern_type": rule.get("pattern_type") or "contains",
            "pattern": rule.get("pattern") or "",
            "language": rule.get("language"),
            "target_route_type": rule.get("target_route_type") or "unknown",
            "target_workflow_id": rule.get("target_workflow_id"),
            "target_task_kind": rule.get("target_task_kind"),
            "target_project_id": rule.get("target_project_id"),
            "constraints": list(rule.get("constraints") or []),
            "positive_examples": list(rule.get("positive_examples") or []),
            "negative_examples": list(rule.get("negative_examples") or []),
            "confidence": rule.get("confidence"),
            "priority": int(rule.get("priority") or 100),
            "status": rule.get("status") or "pending",
            "source": rule.get("source") or "human",
            "source_task_id": rule.get("source_task_id"),
            "source_message": rule.get("source_message"),
            "hit_count": int(rule.get("hit_count") or 0),
            "false_positive_count": int(rule.get("false_positive_count") or 0),
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO routing_rules (
                  id, rule_type, pattern_type, pattern, language, target_route_type,
                  target_workflow_id, target_task_kind, target_project_id, constraints_json,
                  positive_examples_json, negative_examples_json, confidence, priority,
                  status, source, source_task_id, source_message, hit_count,
                  false_positive_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["rule_type"],
                    record["pattern_type"],
                    record["pattern"],
                    record["language"],
                    record["target_route_type"],
                    record["target_workflow_id"],
                    record["target_task_kind"],
                    record["target_project_id"],
                    _json(record["constraints"]),
                    _json(record["positive_examples"]),
                    _json(record["negative_examples"]),
                    record["confidence"],
                    record["priority"],
                    record["status"],
                    record["source"],
                    record["source_task_id"],
                    record["source_message"],
                    record["hit_count"],
                    record["false_positive_count"],
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.get_routing_rule(str(record["id"]))

    def get_routing_rule(self, rule_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM routing_rules WHERE id = ?", (rule_id,)).fetchone()
        if row is None:
            raise KeyError(f"Routing rule not found: {rule_id}")
        return self._row_to_routing_rule(row)

    def list_routing_rules(self, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM routing_rules"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY priority, created_at, id"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_routing_rule(row) for row in rows]

    def update_routing_rule(self, rule_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_routing_rule(rule_id)
        updated = {**current, **patch, "updated_at": utc_now()}
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE routing_rules SET
                  rule_type = ?, pattern_type = ?, pattern = ?, language = ?,
                  target_route_type = ?, target_workflow_id = ?, target_task_kind = ?,
                  target_project_id = ?, constraints_json = ?, positive_examples_json = ?,
                  negative_examples_json = ?, confidence = ?, priority = ?, status = ?,
                  source = ?, source_task_id = ?, source_message = ?, hit_count = ?,
                  false_positive_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated["rule_type"],
                    updated["pattern_type"],
                    updated["pattern"],
                    updated.get("language"),
                    updated["target_route_type"],
                    updated.get("target_workflow_id"),
                    updated.get("target_task_kind"),
                    updated.get("target_project_id"),
                    _json(updated.get("constraints") or []),
                    _json(updated.get("positive_examples") or []),
                    _json(updated.get("negative_examples") or []),
                    updated.get("confidence"),
                    int(updated.get("priority") or 100),
                    updated.get("status") or "pending",
                    updated.get("source") or "human",
                    updated.get("source_task_id"),
                    updated.get("source_message"),
                    int(updated.get("hit_count") or 0),
                    int(updated.get("false_positive_count") or 0),
                    updated["updated_at"].isoformat(),
                    rule_id,
                ),
            )
        return self.get_routing_rule(rule_id)

    def set_routing_rule_status(self, rule_id: str, status: str) -> dict[str, Any]:
        return self.update_routing_rule(rule_id, {"status": status})

    def increment_routing_rule_hit(self, rule_id: str) -> dict[str, Any]:
        rule = self.get_routing_rule(rule_id)
        return self.update_routing_rule(rule_id, {"hit_count": int(rule.get("hit_count") or 0) + 1})

    def add_routing_false_positive(self, rule_id: str, disable_after: int) -> dict[str, Any]:
        rule = self.get_routing_rule(rule_id)
        count = int(rule.get("false_positive_count") or 0) + 1
        patch: dict[str, Any] = {"false_positive_count": count}
        if count >= disable_after:
            patch["status"] = "disabled"
        return self.update_routing_rule(rule_id, patch)

    def create_routing_rule_suggestion(
        self,
        task_id: str | None,
        message: str,
        classifier_result: dict[str, Any],
        suggested_rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = utc_now()
        suggestion_id = new_id("rule-suggestion")
        rule_ids: list[str] = []
        for suggestion in suggested_rules:
            rule = self.create_routing_rule(
                {
                    **suggestion,
                    "status": "pending",
                    "source": "llm_suggested",
                    "source_task_id": task_id,
                    "source_message": message,
                }
            )
            rule_ids.append(str(rule["id"]))
        payload = [{"rule_id": rule_id, **suggestion} for rule_id, suggestion in zip(rule_ids, suggested_rules)]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO routing_rule_suggestions (
                  id, task_id, message, classifier_result_json, suggested_rules_json,
                  status, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    suggestion_id,
                    task_id,
                    message,
                    _json(classifier_result),
                    _json(payload),
                    "pending",
                    now.isoformat(),
                    None,
                ),
            )
        return self.get_routing_rule_suggestion(suggestion_id)

    def get_routing_rule_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM routing_rule_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
        if row is None:
            raise KeyError(f"Routing rule suggestion not found: {suggestion_id}")
        return self._row_to_routing_rule_suggestion(row)

    def list_routing_rule_suggestions(self, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM routing_rule_suggestions"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC, id DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_routing_rule_suggestion(row) for row in rows]

    def set_routing_rule_suggestion_status(self, suggestion_id: str, status: str) -> dict[str, Any]:
        resolved_at = utc_now().isoformat()
        suggestion = self.get_routing_rule_suggestion(suggestion_id)
        rule_status = "active" if status == "promoted" else "rejected"
        for item in suggestion.get("suggested_rules") or []:
            rule_id = item.get("rule_id")
            if rule_id:
                self.set_routing_rule_status(str(rule_id), rule_status)
        with self.connect() as conn:
            conn.execute(
                "UPDATE routing_rule_suggestions SET status = ?, resolved_at = ? WHERE id = ?",
                (status, resolved_at, suggestion_id),
            )
        return self.get_routing_rule_suggestion(suggestion_id)

    def add_routing_feedback(
        self,
        task_id: str | None,
        original_route: dict[str, Any] | None,
        final_route: dict[str, Any] | None,
        user_correction: str | None,
        accepted: bool | None,
    ) -> dict[str, Any]:
        now = utc_now()
        feedback_id = new_id("routing-feedback")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO routing_feedback (
                  id, task_id, original_route_json, final_route_json, user_correction,
                  accepted, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    task_id,
                    _json(original_route) if original_route is not None else None,
                    _json(final_route) if final_route is not None else None,
                    user_correction,
                    None if accepted is None else (1 if accepted else 0),
                    now.isoformat(),
                ),
            )
        return {"id": feedback_id, "task_id": task_id, "accepted": accepted, "created_at": now.isoformat()}

    def add_routing_diagnostic(
        self,
        task_id: str | None,
        message: str,
        deterministic_result: dict[str, Any] | None,
        classifier_result: dict[str, Any] | None,
        final_result: dict[str, Any],
        used_classifier: bool,
    ) -> dict[str, Any]:
        now = utc_now()
        diagnostic_id = new_id("routing-diagnostic")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO routing_diagnostics (
                  id, task_id, message, deterministic_result_json, classifier_result_json,
                  final_result_json, used_classifier, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    diagnostic_id,
                    task_id,
                    message,
                    _json(deterministic_result) if deterministic_result is not None else None,
                    _json(classifier_result) if classifier_result is not None else None,
                    _json(final_result),
                    1 if used_classifier else 0,
                    now.isoformat(),
                ),
            )
        return {
            "id": diagnostic_id,
            "task_id": task_id,
            "message": message,
            "used_classifier": used_classifier,
            "created_at": now.isoformat(),
        }

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

    def create_job(self, task_id: str, action: str, input: dict[str, Any] | None = None) -> TaskJob:
        job = TaskJob(
            id=new_id("job"),
            task_id=task_id,
            action=action,
            status="queued",
            input=input or {},
            created_at=utc_now(),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, task_id, action, status, input_json, result_json, error, created_at, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.task_id,
                    job.action,
                    job.status,
                    _json(job.input),
                    _json(job.result) if job.result is not None else None,
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

    def finish_job(self, job_id: str, status: str, error: str | None = None, result: dict[str, Any] | None = None) -> TaskJob:
        finished_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, result_json = ?, error = ?, finished_at = ? WHERE id = ?",
                (status, _json(result) if result is not None else None, error, finished_at.isoformat(), job_id),
            )
        return self.get_job(job_id)

    def cancel_job(self, job_id: str) -> TaskJob:
        finished_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', finished_at = COALESCE(finished_at, ?)
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (finished_at.isoformat(), job_id),
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

    def add_model_decision(
        self,
        task_id: str | None,
        run_id: str | None,
        operation: str,
        profile: str,
        selected_target: str,
        runtime: str,
        model: str,
        reasoning_effort: str | None,
        reason: str,
        estimated_prompt_chars: int,
        max_prompt_chars: int,
    ) -> ModelDecisionRecord:
        record = ModelDecisionRecord(
            id=new_id("model-decision"),
            task_id=task_id,
            run_id=run_id,
            operation=operation,
            profile=profile,
            selected_target=selected_target,
            runtime=runtime,
            model=model,
            reasoning_effort=reasoning_effort,
            reason=reason,
            estimated_prompt_chars=estimated_prompt_chars,
            max_prompt_chars=max_prompt_chars,
            created_at=utc_now(),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_decisions (
                  id, task_id, run_id, operation, profile, selected_target, runtime,
                  model, reasoning_effort, reason, estimated_prompt_chars, max_prompt_chars, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.task_id,
                    record.run_id,
                    record.operation,
                    record.profile,
                    record.selected_target,
                    record.runtime,
                    record.model,
                    record.reasoning_effort,
                    record.reason,
                    record.estimated_prompt_chars,
                    record.max_prompt_chars,
                    record.created_at.isoformat(),
                ),
            )
        return record

    def list_model_decisions(self, task_id: str) -> list[ModelDecisionRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_decisions WHERE task_id = ? ORDER BY created_at, id",
                (task_id,),
            ).fetchall()
        return [self._row_to_model_decision(row) for row in rows]

    def add_model_call(
        self,
        task_id: str | None,
        run_id: str | None,
        operation: str,
        runtime: str,
        model: str,
        provider: str | None = None,
        reasoning_effort: str | None = None,
        prompt_chars: int = 0,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        cached_prompt_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        total_tokens: int | None = None,
        usage_source: str | None = None,
        usage_is_estimated: bool = False,
        cost_usd: float | None = None,
        latency_ms: int | None = None,
        status: str | None = None,
        error: str | None = None,
    ) -> ModelCallRecord:
        if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        record = ModelCallRecord(
            id=new_id("model-call"),
            task_id=task_id,
            run_id=run_id,
            operation=operation,
            runtime=runtime,
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            prompt_chars=prompt_chars,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_prompt_tokens=cached_prompt_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            usage_source=usage_source,
            usage_is_estimated=usage_is_estimated,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            status=status,
            error=error,
            created_at=utc_now(),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_calls (
                  id, task_id, run_id, operation, runtime, provider, model,
                  reasoning_effort, prompt_chars, prompt_tokens, completion_tokens,
                  cached_prompt_tokens, reasoning_tokens, total_tokens, usage_source,
                  usage_is_estimated, cost_usd, latency_ms, status, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.task_id,
                    record.run_id,
                    record.operation,
                    record.runtime,
                    record.provider,
                    record.model,
                    record.reasoning_effort,
                    record.prompt_chars,
                    record.prompt_tokens,
                    record.completion_tokens,
                    record.cached_prompt_tokens,
                    record.reasoning_tokens,
                    record.total_tokens,
                    record.usage_source,
                    1 if record.usage_is_estimated else 0,
                    record.cost_usd,
                    record.latency_ms,
                    record.status,
                    record.error,
                    record.created_at.isoformat(),
                ),
            )
        return record

    def list_model_calls(self, task_id: str) -> list[ModelCallRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_calls WHERE task_id = ? ORDER BY created_at, id",
                (task_id,),
            ).fetchall()
        return [self._row_to_model_call(row) for row in rows]

    def add_prompt_build(
        self,
        task_id: str | None,
        run_id: str | None,
        operation: str,
        total_chars: int,
        budget_chars: int,
        included: list[dict[str, Any]],
        excluded: list[dict[str, Any]],
        status: str,
    ) -> PromptBuildRecord:
        record = PromptBuildRecord(
            id=new_id("prompt-build"),
            task_id=task_id,
            run_id=run_id,
            operation=operation,
            total_chars=total_chars,
            budget_chars=budget_chars,
            included=included,
            excluded=excluded,
            status=status,
            created_at=utc_now(),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO prompt_builds (
                  id, task_id, run_id, operation, total_chars, budget_chars,
                  included_json, excluded_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.task_id,
                    record.run_id,
                    record.operation,
                    record.total_chars,
                    record.budget_chars,
                    _json(record.included),
                    _json(record.excluded),
                    record.status,
                    record.created_at.isoformat(),
                ),
            )
        return record

    def list_prompt_builds(self, task_id: str) -> list[PromptBuildRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM prompt_builds WHERE task_id = ? ORDER BY created_at, id",
                (task_id,),
            ).fetchall()
        return [self._row_to_prompt_build(row) for row in rows]

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
        correction_request_id: str | None = None,
    ) -> AgentRun:
        run = AgentRun(
            id=new_id("run"),
            task_id=task_id,
            run_type=run_type,
            status=status,
            executor=executor,
            model=model,
            started_at=utc_now(),
            correction_request_id=correction_request_id,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                  id, task_id, run_type, status, executor, model, started_at,
                  finished_at, iteration_count, stop_reason, correction_request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    run.correction_request_id,
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
            task.parent_task_id,
            _json(task.related_task_ids),
            task.correction_source,
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
            parent_task_id=row["parent_task_id"] if "parent_task_id" in row.keys() else None,
            related_task_ids=json.loads(row["related_task_ids_json"])
            if "related_task_ids_json" in row.keys() and row["related_task_ids_json"]
            else [],
            correction_source=row["correction_source"] if "correction_source" in row.keys() else None,
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
            input=json.loads(row["input_json"]) if "input_json" in row.keys() and row["input_json"] else {},
            result=json.loads(row["result_json"]) if "result_json" in row.keys() and row["result_json"] else None,
            error=row["error"],
            created_at=_dt(row["created_at"]),
            started_at=_dt(row["started_at"]),
            finished_at=_dt(row["finished_at"]),
        )

    def _row_to_model_decision(self, row: sqlite3.Row) -> ModelDecisionRecord:
        return ModelDecisionRecord(
            id=row["id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            operation=row["operation"],
            profile=row["profile"],
            selected_target=row["selected_target"],
            runtime=row["runtime"],
            model=row["model"],
            reasoning_effort=row["reasoning_effort"],
            reason=row["reason"] or "",
            estimated_prompt_chars=row["estimated_prompt_chars"] or 0,
            max_prompt_chars=row["max_prompt_chars"] or 0,
            created_at=_dt(row["created_at"]),
        )

    def _row_to_model_call(self, row: sqlite3.Row) -> ModelCallRecord:
        prompt_tokens = row["prompt_tokens"]
        completion_tokens = row["completion_tokens"]
        total_tokens = row["total_tokens"] if "total_tokens" in row.keys() else None
        if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        return ModelCallRecord(
            id=row["id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            operation=row["operation"],
            runtime=row["runtime"],
            provider=row["provider"],
            model=row["model"],
            reasoning_effort=row["reasoning_effort"],
            prompt_chars=row["prompt_chars"] or 0,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_prompt_tokens=row["cached_prompt_tokens"] if "cached_prompt_tokens" in row.keys() else None,
            reasoning_tokens=row["reasoning_tokens"] if "reasoning_tokens" in row.keys() else None,
            total_tokens=total_tokens,
            usage_source=row["usage_source"] if "usage_source" in row.keys() else None,
            usage_is_estimated=bool(row["usage_is_estimated"]) if "usage_is_estimated" in row.keys() else False,
            cost_usd=row["cost_usd"],
            latency_ms=row["latency_ms"],
            status=row["status"],
            error=row["error"],
            created_at=_dt(row["created_at"]),
        )

    def _row_to_prompt_build(self, row: sqlite3.Row) -> PromptBuildRecord:
        return PromptBuildRecord(
            id=row["id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            operation=row["operation"],
            total_chars=row["total_chars"],
            budget_chars=row["budget_chars"],
            included=json.loads(row["included_json"]),
            excluded=json.loads(row["excluded_json"]),
            status=row["status"],
            created_at=_dt(row["created_at"]),
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
            correction_request_id=row["correction_request_id"] if "correction_request_id" in row.keys() else None,
        )

    def _row_to_correction_request(self, row: sqlite3.Row) -> CorrectionRequest:
        return CorrectionRequest(
            id=row["id"],
            task_id=row["task_id"],
            source_gate=row["source_gate"],
            source_approval_id=row["source_approval_id"],
            source_artifact_id=row["source_artifact_id"],
            user_comment=row["user_comment"],
            mode=row["mode"],
            status=row["status"],
            approved_for_execution=bool(row["approved_for_execution"]),
            requires_plan_approval=bool(row["requires_plan_approval"]),
            requires_spec_addendum=bool(row["requires_spec_addendum"]),
            classifier_result=json.loads(row["classifier_result_json"]),
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    def _row_to_routing_rule(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "rule_type": row["rule_type"],
            "pattern_type": row["pattern_type"],
            "pattern": row["pattern"],
            "language": row["language"],
            "target_route_type": row["target_route_type"],
            "target_workflow_id": row["target_workflow_id"],
            "target_task_kind": row["target_task_kind"],
            "target_project_id": row["target_project_id"],
            "constraints": json.loads(row["constraints_json"]) if row["constraints_json"] else [],
            "positive_examples": json.loads(row["positive_examples_json"]) if row["positive_examples_json"] else [],
            "negative_examples": json.loads(row["negative_examples_json"]) if row["negative_examples_json"] else [],
            "confidence": row["confidence"],
            "priority": row["priority"],
            "status": row["status"],
            "source": row["source"],
            "source_task_id": row["source_task_id"],
            "source_message": row["source_message"],
            "hit_count": row["hit_count"],
            "false_positive_count": row["false_positive_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row_to_routing_rule_suggestion(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "message": row["message"],
            "classifier_result": json.loads(row["classifier_result_json"]),
            "suggested_rules": json.loads(row["suggested_rules_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
        }

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
