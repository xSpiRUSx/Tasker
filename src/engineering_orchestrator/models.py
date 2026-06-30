from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


TaskStatus = Literal[
    "created",
    "routing",
    "routed",
    "awaiting_clarification",
    "awaiting_parent_task_clarification",
    "awaiting_tool_health_override",
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
    "awaiting_diff_reapproval",
    "awaiting_scope_escalation_approval",
    "changes_requested",
    "correction_requested",
    "classifying_correction",
    "executing_correction",
    "validating_correction",
    "awaiting_correction_diff_approval",
    "correction_blocked",
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
    "routing_diagnostics",
    "routing_diagnostics_json",
    "clarification_request",
    "context_summary",
    "working_memory",
    "working_memory_json",
    "model_decisions",
    "model_decisions_json",
    "prompt_manifest",
    "tool_health_report",
    "context_compact",
    "context_compact_json",
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
    "scope_escalation",
    "run_report",
    "run_report_json",
    "evaluation_report",
    "repair_prompt",
    "correction_request",
    "correction_context",
    "correction_result",
    "spec_addendum",
    "diagnosis",
    "diff_summary",
    "diff_reapproval",
    "diff_patch",
    "review_report",
    "commit_message",
    "commit_result",
    "package_output",
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
    parent_task_id: str | None = None
    related_task_ids: list[str] = Field(default_factory=list)
    correction_source: str | None = None

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
    input: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
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
    correction_request_id: str | None = None


CorrectionMode = Literal["micro_correction", "minor_correction", "spec_addendum", "new_task"]
CorrectionAction = Literal["run_without_new_plan", "show_plan_first"]


class CorrectionRequest(BaseModel):
    id: str
    task_id: str
    source_gate: str
    source_approval_id: str | None = None
    source_artifact_id: str | None = None
    user_comment: str
    mode: CorrectionMode
    status: str
    approved_for_execution: bool
    requires_plan_approval: bool
    requires_spec_addendum: bool
    classifier_result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CorrectionClassifierResult(BaseModel):
    mode: CorrectionMode
    requires_new_spec: bool = False
    requires_plan_approval: bool = False
    requires_spec_addendum: bool = False
    approved_for_execution: bool = True
    reason: str
    risk_flags: list[str] = Field(default_factory=list)


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


class CreateCorrectionRequest(BaseModel):
    source_gate: str = "diff"
    source_approval_id: str | None = None
    source_artifact_id: str | None = None
    comment: str
    action: CorrectionAction = "run_without_new_plan"


class CreateCorrectionResponse(BaseModel):
    correction_id: str
    mode: CorrectionMode
    status: str
    approved_for_execution: bool
    requires_plan_approval: bool
    requires_spec_addendum: bool


class ContinueTaskRequest(BaseModel):
    message: str


class CancelTaskRequest(BaseModel):
    comment: str | None = None


class ModelDecisionRecord(BaseModel):
    id: str
    task_id: str | None = None
    run_id: str | None = None
    operation: str
    profile: str
    selected_target: str
    runtime: str
    model: str
    reasoning_effort: str | None = None
    reason: str
    estimated_prompt_chars: int = 0
    max_prompt_chars: int = 0
    created_at: datetime


class ModelCallRecord(BaseModel):
    id: str
    task_id: str | None = None
    run_id: str | None = None
    operation: str
    runtime: str
    provider: str | None = None
    model: str
    reasoning_effort: str | None = None
    prompt_chars: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_prompt_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    usage_source: str | None = None
    usage_is_estimated: bool = False
    cost_usd: float | None = None
    latency_ms: int | None = None
    status: str | None = None
    error: str | None = None
    created_at: datetime


class PromptBuildRecord(BaseModel):
    id: str
    task_id: str | None = None
    run_id: str | None = None
    operation: str
    total_chars: int
    budget_chars: int
    included: list[dict[str, Any]] = Field(default_factory=list)
    excluded: list[dict[str, Any]] = Field(default_factory=list)
    status: str
    created_at: datetime
