from __future__ import annotations

from engineering_orchestrator.llm.model_policy import ModelPolicy
from engineering_orchestrator.llm.types import ModelDecision, ModelSelectionRequest
from engineering_orchestrator.services.project_registry import ProjectRegistry


OPERATION_PHASE = {
    "create_simple_plan": "planning",
    "create_1c_bugfix_patch_plan": "planning",
    "create_complex_spec": "planning",
    "create_1c_business_spec": "planning",
    "execute_code": "execution",
    "execute_1c_bugfix_patch": "execution",
    "execute_simple_code_change": "execution",
    "execute_complex_code_change": "execution",
    "execute_micro_correction": "correction",
    "review_diff": "review",
}


class ModelSelector:
    def __init__(self, policy: ModelPolicy, projects: ProjectRegistry | None = None, token_budgets: dict | None = None):
        self.policy = policy
        self.projects = projects
        self.token_budgets = token_budgets or {}

    def select(self, request: ModelSelectionRequest) -> ModelDecision:
        profile = self._profile(request)
        target_id, reason = self._target_id(request, profile)
        target_id, strategy_reason = self._resolve_strategy(target_id)
        if strategy_reason:
            reason = f"{reason}; {strategy_reason}"
        target = self.policy.target(target_id)
        model = self.policy.resolve_model(str(target.get("model") or "none"))
        max_prompt_chars = self._max_prompt_chars(request)
        reasoning_effort = target.get("reasoning_effort")
        if reasoning_effort == "none":
            reasoning_effort = None
        return ModelDecision(
            target_id=target_id,
            runtime=str(target.get("runtime") or "mock"),
            model=model,
            reasoning_effort=str(reasoning_effort) if reasoning_effort else None,
            provider_reasoning_effort=target.get("provider_reasoning_effort"),
            profile=profile,
            operation=request.operation,
            reason=reason,
            max_prompt_chars=max_prompt_chars,
            allow_escalation=self.policy.allows_extra_high(profile),
        )

    def _profile(self, request: ModelSelectionRequest) -> str:
        project = self.projects.get(request.project_id or "") if self.projects and request.project_id else None
        return str((project or {}).get("default_model_profile") or self.policy.active_profile)

    def _target_id(self, request: ModelSelectionRequest, profile: str) -> tuple[str, str]:
        if request.task_override:
            return request.task_override, "task override"

        project = self.projects.get(request.project_id or "") if self.projects and request.project_id else None
        overrides = (project or {}).get("model_overrides") or {}
        override_key = self._project_override_key(request)
        if override_key in overrides:
            return str(overrides[override_key]), f"project override `{override_key}`"

        phase = OPERATION_PHASE.get(request.operation)
        workflow_target = self.policy.workflow_target(request.workflow_id, phase or "", request.correction_mode)
        if workflow_target:
            return workflow_target, f"workflow `{request.workflow_id}` {phase} route"

        operation_target = self.policy.operation_target(request.operation)
        if operation_target:
            return operation_target, f"operation `{request.operation}` route"

        return (
            self.policy.profile_default(profile, request.requires_code_execution),
            f"profile `{profile}` default",
        )

    def _resolve_strategy(self, target_or_strategy: str) -> tuple[str, str | None]:
        if self.policy.is_target(target_or_strategy):
            return target_or_strategy, None
        strategy = self.policy.route_strategy(target_or_strategy)
        if not strategy:
            raise KeyError(f"Unknown model target or route strategy: {target_or_strategy}")
        first = str(strategy.get("first") or "")
        if not first:
            raise KeyError(f"Route strategy `{target_or_strategy}` does not define `first` target.")
        if not self.policy.is_target(first):
            raise KeyError(f"Route strategy `{target_or_strategy}` references unknown target `{first}`.")
        return first, f"strategy `{target_or_strategy}` selected first target `{first}`"

    def _project_override_key(self, request: ModelSelectionRequest) -> str:
        if request.operation == "execute_micro_correction":
            return "correction_micro"
        if request.correction_mode == "minor_correction":
            return "correction_minor"
        if request.operation.startswith("create"):
            return "planning"
        if request.operation.startswith("execute"):
            return "execution"
        if request.operation.startswith("review"):
            return "review"
        return request.operation

    def _max_prompt_chars(self, request: ModelSelectionRequest) -> int:
        project = self.projects.get(request.project_id or "") if self.projects and request.project_id else None
        token_policy = (project or {}).get("token_policy") or {}
        if request.operation == "execute_micro_correction" and token_policy.get("max_correction_prompt_chars"):
            return int(token_policy["max_correction_prompt_chars"])
        if request.operation.startswith("execute") and token_policy.get("max_executor_prompt_chars"):
            return int(token_policy["max_executor_prompt_chars"])
        if request.operation.startswith("review") and token_policy.get("max_diff_chars_for_llm_review"):
            return int(token_policy["max_diff_chars_for_llm_review"])
        operation_budgets = self.token_budgets.get("operation_budgets") or {}
        global_budget = self.token_budgets.get("global") or {}
        return int((operation_budgets.get(request.operation) or {}).get("max_prompt_chars") or global_budget.get("max_prompt_chars") or 300000)
