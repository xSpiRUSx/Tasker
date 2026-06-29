from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Complexity = Literal["trivial", "simple", "medium", "complex", "epic"]
TaskIntent = Literal["question", "investigation", "code_change", "unknown"]
WorkflowIntent = Literal["question", "investigation", "code_change", "unknown", "*"]
ApprovalGate = Literal[
    "clarification",
    "plan",
    "spec",
    "config_change",
    "migration",
    "security_change",
    "diff",
    "commit",
    "deploy_prep",
    "deploy",
]
TaskKind = Literal[
    "question",
    "bugfix",
    "code_patch",
    "linked_correction",
    "feature",
    "refactor",
    "test_update",
    "docs_update",
    "external_report_or_processing",
    "inline_code_or_query",
    "configuration_change",
    "dependency_change",
    "migration",
    "deployment_change",
    "security_change",
    "architecture_change",
    "investigation",
    "unknown",
]
WorkflowTaskKind = Literal[
    "question",
    "bugfix",
    "code_patch",
    "linked_correction",
    "feature",
    "refactor",
    "test_update",
    "docs_update",
    "external_report_or_processing",
    "inline_code_or_query",
    "configuration_change",
    "dependency_change",
    "migration",
    "deployment_change",
    "security_change",
    "architecture_change",
    "investigation",
    "unknown",
    "*",
]
RiskLevel = Literal["low", "medium", "high", "critical"]


class ToolConfig(BaseModel):
    id: str
    name: str
    type: str
    description: str


class ProjectConfig(BaseModel):
    id: str
    name: str
    path: str | None = None
    aliases: list[str] = Field(default_factory=list)
    description: str
    tools: list[str] = Field(default_factory=list)


class WorkflowConfig(BaseModel):
    id: str
    name: str
    description: str
    project_ids: list[str]
    intents: list[WorkflowIntent] = Field(default_factory=lambda: ["*"])
    task_kinds: list[WorkflowTaskKind] = Field(default_factory=lambda: ["*"])
    complexity: list[Complexity]
    required_tools: list[str] = Field(default_factory=list)
    requires_spec: bool = False
    requires_tests: bool = False
    requires_review: bool = False
    requires_config_approval: bool = False
    requires_deploy_prep: bool = False
    approval_gates: list[ApprovalGate] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    allowed_change_types: list[str] = Field(default_factory=list)
    blocked_change_types: list[str] = Field(default_factory=list)
    blocked_task_kinds: list[TaskKind] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)

    def supports_project(self, project_id: str | None) -> bool:
        return "*" in self.project_ids or (project_id is not None and project_id in self.project_ids)

    def supports_complexity(self, complexity: Complexity) -> bool:
        return complexity in self.complexity

    def supports_intent(self, intent: TaskIntent) -> bool:
        return "*" in self.intents or intent in self.intents

    def supports_task_kind(self, task_kind: TaskKind) -> bool:
        blocked = set(self.blocked_task_kinds) | set(self.blocked_change_types)
        return task_kind not in blocked and ("*" in self.task_kinds or task_kind in self.task_kinds)


class RouterConfig(BaseModel):
    tools: dict[str, ToolConfig]
    projects: dict[str, ProjectConfig]
    workflows: dict[str, WorkflowConfig]

    @field_validator("projects")
    @classmethod
    def validate_project_tools(cls, projects: dict[str, ProjectConfig]):
        return projects


class UserTaskAnalysis(BaseModel):
    normalized_task: str = Field(description="Clean, normalized version of the user's request.")
    intent: TaskIntent = Field(description="Primary task intent: question, investigation, code_change, or unknown.")
    task_kind: TaskKind = Field(description="More specific task kind for workflow eligibility.")
    project_id: str | None = Field(description="Best matching project id from config, or null.")
    project_confidence: float = Field(ge=0, le=1)
    complexity: Complexity
    complexity_score: int = Field(ge=1, le=5)
    risk_level: RiskLevel
    risk_flags: list[str] = Field(default_factory=list)
    approval_gates: list[ApprovalGate] = Field(default_factory=list)
    requires_spec: bool
    requires_tests: bool
    requires_review: bool
    requires_config_approval: bool
    requires_deploy_prep: bool
    missing_info: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    workflow_id: str | None = Field(description="Best matching workflow id from config, or null.")
    workflow_confidence: float = Field(ge=0, le=1)
    required_tool_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(description="Short user-visible rationale, without hidden chain-of-thought.")


class RouteDecision(BaseModel):
    input_text: str
    normalized_task: str
    project_id: str | None
    project_name: str | None
    project_path: str | None
    project_confidence: float
    complexity: Complexity
    complexity_score: int
    intent: TaskIntent
    task_kind: TaskKind
    risk_level: RiskLevel
    risk_flags: list[str]
    workflow_id: str | None
    workflow_name: str | None
    workflow_confidence: float
    requires_spec: bool
    requires_tests: bool
    requires_review: bool
    requires_config_approval: bool
    requires_deploy_prep: bool
    approval_gates: list[ApprovalGate]
    recommended_tool_ids: list[str]
    confidence: float
    rationale: str
    missing_info: list[str]
    assumptions: list[str]
    next_steps: list[str]
    warnings: list[str] = Field(default_factory=list)
