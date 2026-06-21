from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


TaskStatus = Literal[
    "created",
    "routing",
    "routed",
    "awaiting_clarification",
    "planning",
    "awaiting_plan_approval",
    "awaiting_spec_approval",
    "awaiting_config_approval",
    "awaiting_migration_approval",
    "awaiting_security_approval",
    "plan_rejected",
    "approved_for_execution",
    "preparing_worktree",
    "executing",
    "validating",
    "reviewing",
    "awaiting_diff_approval",
    "changes_requested",
    "awaiting_commit_approval",
    "approved_for_commit",
    "committing",
    "deploy_prep",
    "awaiting_deploy_approval",
    "closed",
    "failed",
    "cancelled",
]

ArtifactKind = Literal[
    "task_index",
    "request",
    "route_decision",
    "context_summary",
    "spec",
    "todo",
    "test_plan",
    "approval_request",
    "execution_log",
    "validation_report",
    "diff_summary",
    "diff_patch",
    "review_report",
    "commit_message",
    "commit_result",
    "deploy_plan",
    "rollback_plan",
    "final_report",
    "events",
]

ApprovalStatus = Literal["pending", "approved", "rejected", "edited", "cancelled"]


class Task(BaseModel):
    id: str
    status: TaskStatus
    user_message: str
    source: str | None = None
    user_id: str | None = None

    project_id: str | None = None
    project_name: str | None = None
    project_path: str | None = None
    workflow_id: str | None = None
    workflow_name: str | None = None
    risk_level: str | None = None

    route_decision: dict[str, Any] | None = None

    branch_name: str | None = None
    worktree_path: str | None = None
    artifacts_dir: str | None = None

    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


class TaskArtifact(BaseModel):
    id: str
    task_id: str
    kind: ArtifactKind
    version: int | None = None
    title: str
    relative_path: str
    content_type: str = "text/markdown"
    content_hash: str
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None


class Approval(BaseModel):
    id: str
    task_id: str
    gate: str
    status: ApprovalStatus
    artifact_ids: list[str] = Field(default_factory=list)
    requested_payload: dict[str, Any] = Field(default_factory=dict)
    user_comment: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class TaskEvent(BaseModel):
    id: str
    task_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RouteDecision(BaseModel):
    normalized_task: str
    intent: str
    task_kind: str
    complexity: str
    project_id: str | None
    project_name: str | None
    project_path: str | None
    workflow_id: str | None
    workflow_name: str | None
    risk_level: str
    risk_flags: list[str] = Field(default_factory=list)
    approval_gates: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    rationale: str
    requires_spec: bool = False


class CreateTaskRequest(BaseModel):
    message: str
    source: str | None = None
    user_id: str | None = None


class CreateTaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    project_id: str | None
    workflow_id: str | None
    artifacts_dir: str | None
    current_approval_gate: str | None


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = None


class ContinueTaskRequest(BaseModel):
    message: str
