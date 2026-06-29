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
    "validation_failed",
    "awaiting_diff_approval",
    "changes_requested",
    "awaiting_commit_approval",
    "approved_for_commit",
    "committing",
    "deploy_prep",
    "awaiting_deploy_approval",
    "closed",
    "failed",
    "prompt_too_large",
    "cancelled",
]

ArtifactKind = Literal[
    "task_index",
    "request",
    "route_decision",
    "context_summary",
    "working_memory",
    "working_memory_json",
    "answer",
    "spec",
    "todo",
    "test_plan",
    "approval_request",
    "execution_log",
    "executor_policy",
    "executor_prompt",
    "executor_command",
    "executor_stdout",
    "executor_stderr",
    "validation_report",
    "validation_command_output",
    "policy_report",
    "run_report",
    "run_report_json",
    "evaluation_report",
    "repair_prompt",
    "correction_request",
    "correction_context",
    "diagnosis",
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


class TaskJob(BaseModel):
    id: str
    task_id: str
    action: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AgentRun(BaseModel):
    id: str
    task_id: str
    run_type: str
    status: str
    executor: str | None = None
    model: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    iteration_count: int = 0
    stop_reason: str | None = None


class AgentStep(BaseModel):
    id: str
    run_id: str
    step_index: int
    step_type: str
    status: str
    input_summary: str | None = None
    output_summary: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None


class EvaluationResult(BaseModel):
    id: str
    run_id: str
    task_id: str
    passed: bool
    score: float | None = None
    status: str
    findings: list[dict[str, Any]] = Field(default_factory=list)
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


class JobAcceptedResponse(BaseModel):
    accepted: bool = True
    job_id: str
    task_id: str
    status: str
    action: str


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = None


class ContinueTaskRequest(BaseModel):
    message: str


class CancelTaskRequest(BaseModel):
    comment: str | None = None
