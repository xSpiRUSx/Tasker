from __future__ import annotations

from dataclasses import dataclass

from engineering_orchestrator.models import CorrectionAction, CorrectionClassifierResult


RISK_KEYWORDS = {
    "config",
    "configuration",
    "env",
    ".env",
    "secret",
    "security",
    "role",
    "roles",
    "permission",
    "migration",
    "deploy",
}
SPEC_KEYWORDS = {
    "business rule",
    "calculation",
    "calculate",
    "status",
    "workflow",
    "scenario",
    "public api",
    "contract",
    "requirement",
}
NEW_TASK_KEYWORDS = {
    "new feature",
    "separate task",
    "separate report",
    "another report",
    "architecture",
    "redesign",
    "new mechanism",
}
MICRO_KEYWORDS = {
    "rename",
    "remove helper",
    "drop helper",
    "button text",
    "label",
    "one function",
    "unrelated files",
    "extra diff",
}


@dataclass(frozen=True)
class CorrectionClassifierInput:
    comment: str
    action: CorrectionAction = "run_without_new_plan"
    changed_files: list[str] | None = None
    risk_flags: list[str] | None = None
    task_has_approved_plan: bool = True


class CorrectionClassifier:
    def classify(self, data: CorrectionClassifierInput) -> CorrectionClassifierResult:
        comment = data.comment.strip()
        text = comment.lower()
        changed_files = data.changed_files or []
        path_text = " ".join(changed_files).lower()
        explicit_risks = sorted({flag for flag in data.risk_flags or [] if flag})
        keyword_risks = sorted(keyword for keyword in RISK_KEYWORDS if keyword in text or keyword in path_text)
        risk_flags = sorted(set(explicit_risks + keyword_risks))

        if any(keyword in text for keyword in NEW_TASK_KEYWORDS):
            return CorrectionClassifierResult(
                mode="new_task",
                requires_new_spec=True,
                requires_plan_approval=True,
                requires_spec_addendum=False,
                approved_for_execution=False,
                reason="The review comment appears to request a separate feature or architectural change.",
                risk_flags=risk_flags,
            )

        if risk_flags or any(keyword in text for keyword in SPEC_KEYWORDS):
            return CorrectionClassifierResult(
                mode="spec_addendum",
                requires_new_spec=False,
                requires_plan_approval=True,
                requires_spec_addendum=True,
                approved_for_execution=False,
                reason="The correction touches risky areas or changes requirements, so a spec addendum approval is required.",
                risk_flags=risk_flags,
            )

        if data.action == "show_plan_first":
            return CorrectionClassifierResult(
                mode="minor_correction",
                requires_new_spec=False,
                requires_plan_approval=True,
                requires_spec_addendum=False,
                approved_for_execution=False,
                reason="The user requested to see the correction plan before execution.",
                risk_flags=risk_flags,
            )

        mode = "micro_correction" if self._looks_micro(text, changed_files) else "minor_correction"
        return CorrectionClassifierResult(
            mode=mode,
            requires_new_spec=False,
            requires_plan_approval=False,
            requires_spec_addendum=False,
            approved_for_execution=bool(data.task_has_approved_plan),
            reason="User review comment stays within the current reviewed diff and does not expand task scope.",
            risk_flags=risk_flags,
        )

    def _looks_micro(self, text: str, changed_files: list[str]) -> bool:
        if any(keyword in text for keyword in MICRO_KEYWORDS):
            return True
        if len(changed_files) <= 1 and len(text.split()) <= 40:
            return True
        return False
