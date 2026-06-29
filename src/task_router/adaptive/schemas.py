from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RoutingContext(BaseModel):
    task_id: str | None = None
    current_task_id: str | None = None
    source: str | None = None
    source_gate: str | None = None
    ui_action: str | None = None
    recent_task_ids: list[str] = Field(default_factory=list)
    project_hint: str | None = None
    debug: bool = False


class DeterministicRoutingResult(BaseModel):
    route_type: str | None
    project_id: str | None = None
    parent_task_candidates: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    task_kind: str | None = None
    correction_mode: str | None = None
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    matched_rules: list[str] = Field(default_factory=list)
    requires_classifier: bool = False
    requires_clarification: bool = False


class LearnedRuleSuggestion(BaseModel):
    rule_type: str
    language: str | None = None
    pattern_type: Literal["exact", "contains", "regex", "semantic_hint"]
    pattern: str
    constraints: list[str] = Field(default_factory=list)
    positive_examples: list[str] = Field(default_factory=list)
    negative_examples: list[str] = Field(default_factory=list)
    target_route_type: str
    target_workflow_id: str | None = None
    target_task_kind: str | None = None
    confidence: float
    rationale: str


class AdaptiveClassifierResult(BaseModel):
    route_type: Literal[
        "linked_correction",
        "new_task",
        "question",
        "task_action",
        "project_task",
        "unknown",
    ]
    confidence: float
    project_id: str | None = None
    parent_task_candidates: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    task_kind: str | None = None
    correction_mode: str | None = None
    requires_clarification: bool = False
    clarification_question: str | None = None
    reason: str
    learned_rule_suggestions: list[LearnedRuleSuggestion] = Field(default_factory=list)


class AdaptiveRoutingDecision(BaseModel):
    route_type: str
    confidence: float
    project_id: str | None = None
    parent_task_id: str | None = None
    parent_task_candidates: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    task_kind: str | None = None
    correction_mode: str | None = None
    source: Literal[
        "ui_context",
        "explicit_reference",
        "learned_rule",
        "static_rule",
        "cheap_classifier",
        "clarification",
    ]
    used_classifier: bool
    matched_rules: list[str] = Field(default_factory=list)
    suggested_rule_ids: list[str] = Field(default_factory=list)
    requires_clarification: bool = False
    clarification_question: str | None = None
    reason: str
    diagnostics: dict[str, Any] = Field(default_factory=dict)
