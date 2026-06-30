from __future__ import annotations

from typing import Any

from engineering_orchestrator.policies.file_policy import FilePolicyFinding


class EvaluationPolicy:
    def evaluate(
        self,
        executor_status: str,
        validation_status: str,
        changed_files: list[str],
        diff_text: str,
        file_findings: list[FilePolicyFinding],
        max_changed_files: int,
        max_diff_lines: int,
    ) -> tuple[bool, str, list[dict[str, Any]]]:
        findings: list[dict[str, Any]] = [finding.model_dump() for finding in file_findings]
        if executor_status != "success":
            findings.append({"code": "executor_failed", "severity": "error", "message": f"Executor status: {executor_status}"})
        if validation_status == "failed":
            findings.append({"code": "validation_failed", "severity": "error", "message": "Validation commands failed."})
        if validation_status == "manual_review_required":
            findings.append(
                {
                    "code": "manual_review_required",
                    "severity": "warning",
                    "message": "Automated validation was skipped; manual review is required.",
                }
            )
        if len(changed_files) > max_changed_files:
            findings.append(
                {
                    "code": "changed_file_limit_exceeded",
                    "severity": "error",
                    "message": f"Changed file count {len(changed_files)} exceeds limit {max_changed_files}.",
                }
            )
        diff_lines = len(diff_text.splitlines())
        if diff_lines > max_diff_lines:
            findings.append(
                {
                    "code": "diff_line_limit_exceeded",
                    "severity": "error",
                    "message": f"Diff line count {diff_lines} exceeds limit {max_diff_lines}.",
                }
            )

        codes = {finding.get("code") for finding in findings}
        if "blocked_path_changed" in codes or "config_change_requires_approval" in codes:
            return False, "awaiting_human", findings
        if "validation_failed" in codes:
            return False, "repairable", findings
        if "manual_review_required" in codes:
            return False, "manual_review_required", findings
        if findings:
            return False, "failed", findings
        return True, "passed", []
