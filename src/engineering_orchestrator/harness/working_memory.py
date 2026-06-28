from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkingMemory(BaseModel):
    task_id: str
    user_prompt: str
    current_chat_history: list[dict[str, Any]] = Field(default_factory=list)
    system_prompt: str | None = None

    route_decision: dict[str, Any] | None = None
    workflow_policy: dict[str, Any] | None = None
    project_profile: dict[str, Any] | None = None

    procedural_instructions: list[dict[str, Any]] = Field(default_factory=list)
    semantic_facts: list[dict[str, Any]] = Field(default_factory=list)
    episodic_examples: list[dict[str, Any]] = Field(default_factory=list)

    relevant_files: list[dict[str, Any]] = Field(default_factory=list)
    current_artifacts: list[dict[str, Any]] = Field(default_factory=list)

    tool_policy: dict[str, Any] | None = None
    approval_gates: list[str] = Field(default_factory=list)
    stop_conditions: dict[str, Any] | None = None
