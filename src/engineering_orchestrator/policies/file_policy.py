from __future__ import annotations

from fnmatch import fnmatch
from typing import Any

from pydantic import BaseModel


DEFAULT_BLOCKED_PATTERNS = [
    ".env",
    ".env.*",
    "**/secrets/**",
    "**/*secret*",
    "**/*password*",
    "**/migrations/**",
    "**/alembic/**",
    ".github/workflows/**",
    "infra/**",
    "deploy/**",
]

DEFAULT_CONFIG_PATTERNS = ["*.yml", "*.yaml", "*.json", "**/*.yml", "**/*.yaml", "**/*.json"]


class FilePolicyFinding(BaseModel):
    code: str
    path: str
    severity: str
    message: str


class FilePolicy:
    def __init__(self, project: dict[str, Any] | None = None, workflow: dict[str, Any] | None = None):
        self.project = project or {}
        self.workflow = workflow or {}

    def evaluate(self, changed_files: list[str], approved_gates: set[str] | None = None) -> list[FilePolicyFinding]:
        approved_gates = approved_gates or set()
        findings: list[FilePolicyFinding] = []
        blocked_patterns = [*DEFAULT_BLOCKED_PATTERNS, *[str(item) for item in self.project.get("blocked_paths", [])]]
        config_patterns = [*DEFAULT_CONFIG_PATTERNS, *[str(item) for item in self.project.get("config_paths", [])]]
        blocked_change_types = set(self.workflow.get("blocked_change_types", []))

        for path in changed_files:
            normalized = path.replace("\\", "/")
            if any(_matches(normalized, pattern) for pattern in blocked_patterns):
                findings.append(
                    FilePolicyFinding(
                        code="blocked_path_changed",
                        path=path,
                        severity="error",
                        message=f"Blocked path changed: `{path}`.",
                    )
                )
            if (
                "configuration_change" in blocked_change_types
                and "config_change" not in approved_gates
                and any(_matches(normalized, pattern) for pattern in config_patterns)
            ):
                findings.append(
                    FilePolicyFinding(
                        code="config_change_requires_approval",
                        path=path,
                        severity="warning",
                        message=f"Configuration path changed without config approval: `{path}`.",
                    )
                )
        return findings


def _matches(path: str, pattern: str) -> bool:
    normalized_pattern = pattern.replace("\\", "/")
    return path == normalized_pattern or fnmatch(path, normalized_pattern)
