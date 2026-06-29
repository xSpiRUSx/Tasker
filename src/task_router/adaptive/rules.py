from __future__ import annotations

import re
from typing import Any

from task_router.adaptive.deterministic import (
    extract_task_references,
    has_action_signal,
    has_correction_signal,
    has_question_signal,
)
from task_router.adaptive.schemas import DeterministicRoutingResult


def rule_matches(rule: dict[str, Any], message: str, context: dict[str, Any] | None = None) -> bool:
    if str(rule.get("status") or "") != "active":
        return False
    if _matches_negative(rule, message):
        return False
    if not _pattern_matches(str(rule.get("pattern_type") or "contains"), str(rule.get("pattern") or ""), message):
        return False
    constraints = _constraints(rule)
    return all(_constraint_passes(name, message, context or {}) for name in constraints)


def result_from_rule(rule: dict[str, Any], message: str) -> DeterministicRoutingResult:
    refs = extract_task_references(message)
    return DeterministicRoutingResult(
        route_type=str(rule.get("target_route_type") or "unknown"),
        project_id=rule.get("target_project_id"),
        parent_task_candidates=refs,
        workflow_id=rule.get("target_workflow_id"),
        task_kind=rule.get("target_task_kind"),
        correction_mode="micro_correction" if rule.get("target_route_type") == "linked_correction" else None,
        confidence=max(float(rule.get("confidence") or 0.90), 0.90),
        reasons=[f"Matched learned routing rule `{rule.get('id')}`."],
        matched_rules=[str(rule.get("id"))],
    )


def _pattern_matches(pattern_type: str, pattern: str, message: str) -> bool:
    if not pattern:
        return False
    if pattern_type == "exact":
        return message == pattern
    if pattern_type in {"contains", "semantic_hint"}:
        return pattern in message
    if pattern_type == "regex":
        try:
            return re.search(pattern, message) is not None
        except re.error:
            return False
    return False


def _matches_negative(rule: dict[str, Any], message: str) -> bool:
    for example in rule.get("negative_examples") or []:
        normalized = str(example).strip().lower().replace("ё", "е")
        if normalized and (message == normalized or normalized in message):
            return True
    return False


def _constraints(rule: dict[str, Any]) -> list[str]:
    constraints = rule.get("constraints")
    if isinstance(constraints, list):
        return [str(item) for item in constraints]
    return []


def _constraint_passes(name: str, message: str, context: dict[str, Any]) -> bool:
    if name == "task_ref_exists":
        return bool(extract_task_references(message))
    if name == "has_correction_signal":
        return has_correction_signal(message)
    if name == "has_question_signal":
        return has_question_signal(message)
    if name == "has_action_signal":
        return has_action_signal(message)
    if name == "current_user_has_task_context":
        return bool(context.get("current_task_id"))
    if name in {"project_exists", "parent_task_project_matches", "not_status_closed_or_cancelled"}:
        return True
    return False
