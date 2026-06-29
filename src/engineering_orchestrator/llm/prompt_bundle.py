from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PromptBundle(BaseModel):
    task_id: str | None
    run_id: str | None = None
    operation: str
    prompt: str
    total_chars: int
    budget_chars: int
    included_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    excluded_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    model_decision_id: str | None = None
    context_manifest_id: str | None = None
    prompt_build_id: str | None = None
