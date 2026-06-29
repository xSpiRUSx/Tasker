from __future__ import annotations

import json
from typing import Any, Protocol

from task_router.adaptive.config import CheapClassifierConfig
from task_router.adaptive.deterministic import (
    extract_task_references,
    has_correction_signal,
    has_new_task_signal,
    has_question_signal,
)
from task_router.adaptive.schemas import AdaptiveClassifierResult, DeterministicRoutingResult, LearnedRuleSuggestion, RoutingContext


class CheapClassifierProvider(Protocol):
    def classify(self, prompt: str) -> AdaptiveClassifierResult:
        pass


class CheapClassifier:
    def __init__(self, provider: CheapClassifierProvider | None = None):
        self.provider = provider

    def classify(
        self,
        message: str,
        context: RoutingContext,
        deterministic: DeterministicRoutingResult,
        projects: list[dict[str, Any]],
        recent_tasks: list[dict[str, Any]],
        active_rules: list[dict[str, Any]],
        config: CheapClassifierConfig,
    ) -> tuple[AdaptiveClassifierResult, str]:
        prompt = build_classifier_prompt(message, context, deterministic, projects, recent_tasks, active_rules, config)
        if self.provider is not None:
            return self.provider.classify(prompt), prompt
        return self._local_fallback(message, deterministic), prompt

    def _local_fallback(self, message: str, deterministic: DeterministicRoutingResult) -> AdaptiveClassifierResult:
        refs = extract_task_references(message)
        if refs and has_question_signal(message) and not has_correction_signal(message):
            return AdaptiveClassifierResult(
                route_type="question",
                confidence=0.82,
                parent_task_candidates=refs,
                reason="Local cheap-classifier fallback found task question intent.",
            )
        if refs and has_new_task_signal(message):
            return AdaptiveClassifierResult(
                route_type="new_task",
                confidence=0.78,
                parent_task_candidates=refs,
                task_kind="linked_task",
                requires_clarification=True,
                clarification_question="Is this a correction to the referenced task or a new linked task?",
                reason="Local fallback found linked-new-task wording but confidence is below accept threshold.",
            )
        if refs and has_correction_signal(message):
            suggestion = LearnedRuleSuggestion(
                rule_type="intent_pattern",
                language="ru",
                pattern_type="contains",
                pattern=_suggest_contains_pattern(message),
                constraints=["task_ref_exists", "has_correction_signal"],
                positive_examples=[message],
                negative_examples=["покажи задачу 00011", "что было в задаче 00011?", "закрой задачу 00011"],
                target_route_type="linked_correction",
                target_workflow_id="task_correction",
                target_task_kind="linked_correction",
                confidence=0.84,
                rationale="Correction wording appears near an explicit task reference.",
            )
            return AdaptiveClassifierResult(
                route_type="linked_correction",
                confidence=0.87,
                parent_task_candidates=refs,
                workflow_id="task_correction",
                task_kind="linked_correction",
                correction_mode="micro_correction",
                reason="Local cheap-classifier fallback inferred linked correction from correction intent and task reference.",
                learned_rule_suggestions=[suggestion],
            )
        return AdaptiveClassifierResult(
            route_type=deterministic.route_type or "unknown",
            confidence=max(0.0, min(deterministic.confidence, 0.59)),
            parent_task_candidates=deterministic.parent_task_candidates,
            requires_clarification=True,
            clarification_question="Should Tasker treat this as a correction to an existing task or as a new task?",
            reason="Local cheap-classifier fallback could not route confidently.",
        )


def build_classifier_prompt(
    message: str,
    context: RoutingContext,
    deterministic: DeterministicRoutingResult,
    projects: list[dict[str, Any]],
    recent_tasks: list[dict[str, Any]],
    active_rules: list[dict[str, Any]],
    config: CheapClassifierConfig,
) -> str:
    payload = {
        "instruction": "Classify a Tasker routing request. Return only JSON matching AdaptiveClassifierResult.",
        "user_message": message,
        "context": context.model_dump(mode="json"),
        "deterministic_candidate": deterministic.model_dump(mode="json"),
        "available_route_types": ["linked_correction", "new_task", "question", "task_action", "project_task", "unknown"],
        "excluded_context": ["source_code", "diffs", "runtime_logs", "events", "artifacts"],
        "projects": _project_summary(projects) if config.include_project_aliases else [],
        "recent_tasks": recent_tasks[: config.recent_tasks_limit] if config.include_recent_tasks else [],
        "active_rules": _rule_summary(active_rules) if config.include_active_rules else [],
        "schema": {
            "route_type": "linked_correction | new_task | question | task_action | project_task | unknown",
            "confidence": "float 0..1",
            "learned_rule_suggestions": "array of pending rule suggestions",
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(text) <= config.max_prompt_chars:
        return text
    compact_payload = dict(payload)
    compact_payload["recent_tasks"] = (compact_payload["recent_tasks"] or [])[:5]
    compact_payload["active_rules"] = (compact_payload["active_rules"] or [])[:10]
    text = json.dumps(compact_payload, ensure_ascii=False, indent=2)
    if len(text) > config.max_prompt_chars:
        compact_payload["recent_tasks"] = []
        compact_payload["active_rules"] = []
        text = json.dumps(compact_payload, ensure_ascii=False, indent=2)
    return text[: config.max_prompt_chars]


def _project_summary(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "aliases": list(item.get("aliases") or [])[:10],
        }
        for item in projects
    ]


def _rule_summary(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "pattern_type": item.get("pattern_type"),
            "pattern": item.get("pattern"),
            "target_route_type": item.get("target_route_type"),
            "constraints": item.get("constraints") or [],
        }
        for item in rules
    ]


def _suggest_contains_pattern(message: str) -> str:
    lowered = message.lower().replace("ё", "е")
    for signal in ["нужны правки", "есть замечания", "ошибка", "исправ"]:
        if signal in lowered:
            return signal
    return "правк" if "правк" in lowered else "ошибка"
