from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any


PRODUCTION_PATTERNS = [
    "src/cfe/CommonModules/**",
    "src/cfe/Documents/**",
    "src/cfe/Catalogs/**",
    "src/cfe/InformationRegisters/**",
    "src/cfe/AccumulationRegisters/**",
    "src/cfe/Roles/**",
    "src/cfe/ExchangePlans/**",
]

ALLOWED_EXTERNAL_PATTERNS = ["src/epf/**", "src/reports/**", "docs/**"]


@dataclass(frozen=True)
class ScopeEscalationResult:
    scope_escalated: bool
    gate: str | None = None
    reason: str | None = None
    changed_files: list[str] = field(default_factory=list)


class ScopeEscalationDetector:
    def detect(
        self,
        user_message: str,
        workflow_id: str | None,
        changed_files: list[str],
        route_decision: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> ScopeEscalationResult:
        if not self._external_processing_intent(user_message, workflow_id, route_decision):
            return ScopeEscalationResult(scope_escalated=False)

        production_patterns = list((policy or {}).get("production_paths") or PRODUCTION_PATTERNS)
        production_changes = [
            file_name
            for file_name in changed_files
            if any(self._matches(file_name, pattern) for pattern in production_patterns)
        ]
        if not production_changes:
            return ScopeEscalationResult(scope_escalated=False)

        return ScopeEscalationResult(
            scope_escalated=True,
            gate=str((policy or {}).get("gate") or "scope_escalation"),
            reason="User requested external processing/testing output, but production configuration modules were changed.",
            changed_files=production_changes,
        )

    def _external_processing_intent(
        self,
        user_message: str,
        workflow_id: str | None,
        route_decision: dict[str, Any] | None,
    ) -> bool:
        task_kind = str((route_decision or {}).get("task_kind") or "")
        if workflow_id in {"simple_external_development", "1c_external_processing"}:
            return True
        if task_kind in {"external_report_or_processing", "1c_external_processing"}:
            return True
        text = user_message.lower()
        return any(token in text for token in ["external processing", "epf", "external report", "внешн"])

    def _matches(self, path: str, pattern: str) -> bool:
        normalized = path.replace("\\", "/")
        return fnmatch(normalized, pattern.replace("\\", "/"))
