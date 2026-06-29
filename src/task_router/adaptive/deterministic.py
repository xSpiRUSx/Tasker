from __future__ import annotations

import re
from typing import Iterable

from task_router.adaptive.schemas import DeterministicRoutingResult, RoutingContext


FULL_TASK_RE = re.compile(r"\b[A-Z]+-\d{4}-\d{5}\b", re.IGNORECASE)
SHORT_TASK_RE = re.compile(r"(?<!\d)(\d{5})(?!\d)")

CORRECTION_SIGNALS = [
    "замечани",
    "ошибка",
    "исправ",
    "правк",
    "доработ",
    "падает",
    "сломал",
    "не работает",
    "bug",
    "fix",
    "regression",
    "broken",
    "changes requested",
]
QUESTION_SIGNALS = [
    "покажи",
    "что было",
    "что в",
    "расскажи",
    "статус",
    "show",
    "what",
    "why",
    "status",
    "?",
]
ACTION_SIGNALS = ["закрой", "отмени", "approve", "reject", "cancel", "close"]
NEW_TASK_SIGNALS = ["создай продолжение", "новая задача", "linked task", "new task", "продолжение задачи"]


def extract_task_references(message: str) -> list[str]:
    refs: list[str] = []
    refs.extend(match.group(0).upper() for match in FULL_TASK_RE.finditer(message))
    refs.extend(match.group(1) for match in SHORT_TASK_RE.finditer(message))
    seen: set[str] = set()
    return [ref for ref in refs if not (ref in seen or seen.add(ref))]


def has_any(text: str, signals: Iterable[str]) -> bool:
    return any(signal in text for signal in signals)


def has_correction_signal(text: str) -> bool:
    return has_any(text, CORRECTION_SIGNALS)


def has_question_signal(text: str) -> bool:
    stripped = text.strip()
    return stripped.endswith("?") or has_any(text, QUESTION_SIGNALS)


def has_action_signal(text: str) -> bool:
    return has_any(text, ACTION_SIGNALS)


def has_new_task_signal(text: str) -> bool:
    return has_any(text, NEW_TASK_SIGNALS)


def route_from_ui_context(context: RoutingContext) -> DeterministicRoutingResult | None:
    if not context.current_task_id:
        return None
    if context.ui_action in {"request_changes_and_run", "request_changes", "run_correction"} or context.source_gate:
        return DeterministicRoutingResult(
            route_type="linked_correction",
            parent_task_candidates=[context.current_task_id],
            workflow_id="task_correction",
            task_kind="linked_correction",
            correction_mode="micro_correction",
            confidence=1.0,
            reasons=["UI context supplied current task and correction action."],
            matched_rules=["ui_context_correction"],
        )
    return None


def static_route(message: str, context: RoutingContext) -> DeterministicRoutingResult:
    refs = extract_task_references(message)
    correction = has_correction_signal(message)
    question = has_question_signal(message)
    action = has_action_signal(message)
    new_task = has_new_task_signal(message)

    if refs and question and not correction:
        return DeterministicRoutingResult(
            route_type="question",
            parent_task_candidates=refs,
            confidence=0.88,
            reasons=["Task reference plus question signal."],
            matched_rules=["static_task_question"],
        )
    if refs and action and not correction:
        return DeterministicRoutingResult(
            route_type="task_action",
            parent_task_candidates=refs,
            confidence=0.88,
            reasons=["Task reference plus action signal."],
            matched_rules=["static_task_action"],
        )
    if refs and new_task:
        return DeterministicRoutingResult(
            route_type="new_task",
            parent_task_candidates=refs,
            task_kind="linked_task",
            confidence=0.82,
            reasons=["Task reference plus new linked task signal."],
            matched_rules=["static_linked_new_task"],
            requires_classifier=True,
        )
    if refs and correction:
        strong = any(signal in message for signal in ["замечани", "ошибка", "исправ", "bug", "fix"])
        return DeterministicRoutingResult(
            route_type="linked_correction",
            parent_task_candidates=refs,
            workflow_id="task_correction",
            task_kind="linked_correction",
            correction_mode="micro_correction",
            confidence=0.86 if strong else 0.72,
            reasons=["Task reference plus correction signal."],
            matched_rules=["static_linked_correction"],
            requires_classifier=not strong,
        )
    if refs:
        return DeterministicRoutingResult(
            route_type="unknown",
            parent_task_candidates=refs,
            confidence=0.52,
            reasons=["Task reference found, but intent is ambiguous."],
            matched_rules=["static_task_reference"],
            requires_classifier=True,
        )
    if context.project_hint:
        return DeterministicRoutingResult(
            route_type="project_task",
            project_id=context.project_hint,
            confidence=0.70,
            reasons=["Project hint supplied without a clear workflow."],
            requires_classifier=True,
        )
    return DeterministicRoutingResult(
        route_type="unknown",
        confidence=0.40,
        reasons=["No deterministic adaptive route matched."],
        requires_classifier=True,
    )
