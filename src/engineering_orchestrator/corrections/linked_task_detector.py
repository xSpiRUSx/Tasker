from __future__ import annotations

import re

from pydantic import BaseModel


FULL_TASK_RE = re.compile(r"\b([A-Z]{2,12}-\d{4}-\d{5,})\b", re.IGNORECASE)
NUMERIC_TASK_RE = re.compile(
    r"(?:\b(?:task|issue|задач[аеуы]|по\s+задач[еуы]|после\s+задачи)\s*)\b(\d{4,6})\b",
    re.IGNORECASE,
)
BARE_NUMERIC_RE = re.compile(r"\b(\d{5})\b")

CORRECTION_HINTS = [
    "замечан",
    "исправ",
    "после ревью",
    "по diff",
    "по дифф",
    "после отклонения",
    "review comment",
    "changes requested",
    "fix review",
    "address review",
]

PREVIOUS_TASK_HINTS = [
    "предыдущей задаче",
    "прошлой задаче",
    "previous task",
    "last task",
]


class LinkedTaskDetectionResult(BaseModel):
    found: bool
    parent_task_id: str | None = None
    confidence: float
    reason: str
    extracted_reference: str | None = None
    needs_latest_task_lookup: bool = False


class LinkedTaskDetector:
    def detect(self, message: str) -> LinkedTaskDetectionResult:
        text = message.strip()
        lower = text.lower()

        full = FULL_TASK_RE.search(text)
        if full:
            task_id = full.group(1).upper()
            return LinkedTaskDetectionResult(
                found=True,
                parent_task_id=task_id,
                confidence=0.98,
                reason=f"Message references explicit task id `{task_id}`.",
                extracted_reference=task_id,
            )

        numeric = NUMERIC_TASK_RE.search(lower) or (BARE_NUMERIC_RE.search(lower) if self._has_correction_hint(lower) else None)
        if numeric:
            reference = numeric.group(1)
            return LinkedTaskDetectionResult(
                found=True,
                confidence=0.86 if self._has_correction_hint(lower) else 0.78,
                reason=f"Message references task number `{reference}`.",
                extracted_reference=reference,
            )

        if self._has_correction_hint(lower) and any(hint in lower for hint in PREVIOUS_TASK_HINTS):
            return LinkedTaskDetectionResult(
                found=True,
                confidence=0.72,
                reason="Message asks for corrections to the previous task.",
                extracted_reference="previous_task",
                needs_latest_task_lookup=True,
            )

        return LinkedTaskDetectionResult(
            found=False,
            confidence=0.0,
            reason="No linked task reference was detected.",
        )

    def _has_correction_hint(self, lower: str) -> bool:
        return any(hint in lower for hint in CORRECTION_HINTS)
