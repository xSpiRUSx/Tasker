from __future__ import annotations

from engineering_orchestrator.executors.base import ExecutionResult


class ReviewService:
    def mock_review(self, result: ExecutionResult) -> str:
        changed = ", ".join(result.changed_files) if result.changed_files else "No files changed."
        return f"Mock review completed.\n\nChanged files: {changed}\n\nSummary: {result.summary}"
