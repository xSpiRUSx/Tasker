from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelSelectionRequest(BaseModel):
    task_id: str | None = None
    operation: str
    workflow_id: str | None = None
    project_id: str | None = None
    complexity: str | None = None
    risk_level: str | None = None
    correction_mode: str | None = None
    estimated_prompt_chars: int = 0
    requires_code_execution: bool = False
    task_override: str | None = None


class ModelDecision(BaseModel):
    target_id: str
    runtime: str
    model: str
    reasoning_effort: str | None
    provider_reasoning_effort: str | None = None
    profile: str
    operation: str
    reason: str
    max_prompt_chars: int
    allow_escalation: bool


class PromptArtifactEntry(BaseModel):
    kind: str
    version: int | None = None
    chars: int = 0
    path: str | None = None
    reason: str | None = None


class ContextManifest(BaseModel):
    operation: str
    included_artifacts: list[PromptArtifactEntry] = Field(default_factory=list)
    excluded_artifacts: list[PromptArtifactEntry] = Field(default_factory=list)
    total_chars: int
    budget_chars: int
    status: str
    details: dict[str, Any] = Field(default_factory=dict)
