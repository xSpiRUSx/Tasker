from __future__ import annotations

from typing import Any, Callable

from task_router.adaptive.cheap_classifier import CheapClassifier
from task_router.adaptive.config import AdaptiveRoutingConfig
from task_router.adaptive.deterministic import route_from_ui_context, static_route
from task_router.adaptive.normalizer import normalize_message
from task_router.adaptive.rules import result_from_rule, rule_matches
from task_router.adaptive.schemas import AdaptiveClassifierResult, AdaptiveRoutingDecision, DeterministicRoutingResult, RoutingContext


TaskResolver = Callable[[list[str], RoutingContext], tuple[str | None, list[str], str | None]]


class AdaptiveRoutingService:
    def __init__(
        self,
        config: AdaptiveRoutingConfig | None = None,
        cheap_classifier: CheapClassifier | None = None,
        task_resolver: TaskResolver | None = None,
    ):
        self.config = config or AdaptiveRoutingConfig()
        self.cheap_classifier = cheap_classifier or CheapClassifier()
        self.task_resolver = task_resolver

    def route(
        self,
        message: str,
        context: RoutingContext | None = None,
        *,
        active_rules: list[dict[str, Any]] | None = None,
        projects: list[dict[str, Any]] | None = None,
        recent_tasks: list[dict[str, Any]] | None = None,
        save_suggestions: Callable[[AdaptiveClassifierResult], list[str]] | None = None,
    ) -> AdaptiveRoutingDecision:
        context = context or RoutingContext()
        normalized = normalize_message(message, self.config.normalization)
        active_rules = active_rules or []
        projects = projects or []
        recent_tasks = recent_tasks or []

        ui_result = route_from_ui_context(context)
        if ui_result:
            decision = self._decision_from_deterministic(ui_result, context, "ui_context", False)
            decision.diagnostics = self._diagnostics(message, normalized, ui_result, None, decision)
            return decision

        learned = self._apply_learned_rules(normalized, context, active_rules)
        if learned and learned.confidence >= self.config.confidence_thresholds.accept_deterministic:
            decision = self._decision_from_deterministic(learned, context, "learned_rule", False)
            decision.diagnostics = self._diagnostics(message, normalized, learned, None, decision)
            return decision

        deterministic = static_route(normalized, context)
        if deterministic.confidence >= self.config.confidence_thresholds.accept_deterministic:
            decision = self._decision_from_deterministic(deterministic, context, "static_rule", False)
            decision.diagnostics = self._diagnostics(message, normalized, deterministic, None, decision)
            return decision

        classifier_result: AdaptiveClassifierResult | None = None
        prompt = ""
        should_call_classifier = (
            self.config.cheap_classifier.enabled
            and deterministic.confidence < self.config.confidence_thresholds.call_cheap_classifier_below
        )
        if should_call_classifier:
            classifier_result, prompt = self.cheap_classifier.classify(
                normalized,
                context,
                deterministic,
                projects,
                recent_tasks,
                active_rules,
                self.config.cheap_classifier,
            )
            suggested_ids = save_suggestions(classifier_result) if save_suggestions else []
            if (
                classifier_result.confidence >= self.config.confidence_thresholds.call_cheap_classifier_below
                and not classifier_result.requires_clarification
            ):
                decision = self._decision_from_classifier(classifier_result, context, suggested_ids)
                decision.diagnostics = self._diagnostics(message, normalized, deterministic, classifier_result, decision, prompt)
                return decision

        decision = self._clarification_decision(deterministic, classifier_result, context)
        decision.diagnostics = self._diagnostics(message, normalized, deterministic, classifier_result, decision, prompt)
        return decision

    def _apply_learned_rules(
        self,
        normalized: str,
        context: RoutingContext,
        active_rules: list[dict[str, Any]],
    ) -> DeterministicRoutingResult | None:
        for rule in sorted(active_rules, key=lambda item: int(item.get("priority") or 100)):
            if rule_matches(rule, normalized, context.model_dump(mode="json")):
                return result_from_rule(rule, normalized)
        return None

    def _decision_from_deterministic(
        self,
        result: DeterministicRoutingResult,
        context: RoutingContext,
        source: str,
        used_classifier: bool,
    ) -> AdaptiveRoutingDecision:
        parent_task_id, candidates, warning = self._resolve_parent(result.parent_task_candidates, context)
        reason = "; ".join(result.reasons)
        if warning:
            reason = f"{reason} {warning}".strip()
        return AdaptiveRoutingDecision(
            route_type=result.route_type or "unknown",
            confidence=result.confidence,
            project_id=result.project_id,
            parent_task_id=parent_task_id,
            parent_task_candidates=candidates,
            workflow_id=result.workflow_id,
            task_kind=result.task_kind,
            correction_mode=result.correction_mode,
            source=source,  # type: ignore[arg-type]
            used_classifier=used_classifier,
            matched_rules=result.matched_rules,
            requires_clarification=bool(result.requires_clarification or warning),
            clarification_question="Which task should this refer to?" if warning else None,
            reason=reason or "Deterministic adaptive route matched.",
        )

    def _decision_from_classifier(
        self,
        result: AdaptiveClassifierResult,
        context: RoutingContext,
        suggested_ids: list[str],
    ) -> AdaptiveRoutingDecision:
        parent_task_id, candidates, warning = self._resolve_parent(result.parent_task_candidates, context)
        return AdaptiveRoutingDecision(
            route_type=result.route_type,
            confidence=result.confidence,
            project_id=result.project_id,
            parent_task_id=parent_task_id,
            parent_task_candidates=candidates,
            workflow_id=result.workflow_id,
            task_kind=result.task_kind,
            correction_mode=result.correction_mode,
            source="cheap_classifier",
            used_classifier=True,
            suggested_rule_ids=suggested_ids,
            requires_clarification=bool(result.requires_clarification or warning),
            clarification_question=result.clarification_question or ("Which task should this refer to?" if warning else None),
            reason=result.reason if not warning else f"{result.reason} {warning}",
        )

    def _clarification_decision(
        self,
        deterministic: DeterministicRoutingResult,
        classifier: AdaptiveClassifierResult | None,
        context: RoutingContext,
    ) -> AdaptiveRoutingDecision:
        candidates = classifier.parent_task_candidates if classifier else deterministic.parent_task_candidates
        parent_task_id, resolved_candidates, warning = self._resolve_parent(candidates, context)
        route_type = classifier.route_type if classifier else (deterministic.route_type or "unknown")
        confidence = classifier.confidence if classifier else deterministic.confidence
        question = (
            classifier.clarification_question
            if classifier and classifier.clarification_question
            else "Is this a correction to an existing task or a new task?"
        )
        if warning:
            question = "Which existing task should this request use as parent?"
        reason = (classifier.reason if classifier else "; ".join(deterministic.reasons)) or "Adaptive routing needs clarification."
        if warning:
            reason = f"{reason} {warning}".strip()
        return AdaptiveRoutingDecision(
            route_type=route_type,
            confidence=confidence,
            parent_task_id=parent_task_id,
            parent_task_candidates=resolved_candidates,
            workflow_id=classifier.workflow_id if classifier else deterministic.workflow_id,
            task_kind=classifier.task_kind if classifier else deterministic.task_kind,
            correction_mode=classifier.correction_mode if classifier else deterministic.correction_mode,
            source="clarification",
            used_classifier=classifier is not None,
            requires_clarification=True,
            clarification_question=question,
            reason=reason,
        )

    def _resolve_parent(self, refs: list[str], context: RoutingContext) -> tuple[str | None, list[str], str | None]:
        if not refs:
            return context.current_task_id if context.current_task_id else None, [], None
        if self.task_resolver is None:
            return refs[0], refs, None
        return self.task_resolver(refs, context)

    def _diagnostics(
        self,
        message: str,
        normalized: str,
        deterministic: DeterministicRoutingResult,
        classifier: AdaptiveClassifierResult | None,
        decision: AdaptiveRoutingDecision,
        prompt: str = "",
    ) -> dict[str, Any]:
        return {
            "message": message,
            "normalized_message": normalized,
            "deterministic_result": deterministic.model_dump(mode="json"),
            "classifier_result": classifier.model_dump(mode="json") if classifier else None,
            "final_result": decision.model_dump(mode="json", exclude={"diagnostics"}),
            "used_classifier": classifier is not None,
            "classifier_prompt_chars": len(prompt),
        }
