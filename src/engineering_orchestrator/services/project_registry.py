from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ProjectRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = yaml.safe_load(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"projects": []}
        self.projects: list[dict[str, Any]] = self.data.get("projects", [])

    def find_for_message(self, message: str) -> dict[str, Any] | None:
        haystack = message.lower()
        for project in self.projects:
            tokens = [project.get("id", ""), project.get("name", ""), *project.get("aliases", [])]
            if any(str(token).lower() in haystack for token in tokens if token):
                return project
        return self.get("generic") or (self.projects[0] if self.projects else None)

    def get(self, project_id: str) -> dict[str, Any] | None:
        return next((project for project in self.projects if project.get("id") == project_id), None)

    def test_commands(self, project_id: str | None) -> list[str]:
        project = self.get(project_id) if project_id else None
        return [str(command) for command in (project or {}).get("test_commands", [])]

    def validation_profile(self, project_id: str | None) -> str:
        project = self.get(project_id) if project_id else None
        return str((project or {}).get("validation_profile", "generic"))

    def blocked_paths(self, project_id: str | None) -> list[str]:
        project = self.get(project_id) if project_id else None
        defaults = [".env", ".env.*", "secrets/**", "**/secrets/**"]
        return [*defaults, *[str(pattern) for pattern in (project or {}).get("blocked_paths", [])]]

    def allowed_paths(self, project_id: str | None) -> list[str]:
        project = self.get(project_id) if project_id else None
        return [str(pattern) for pattern in (project or {}).get("allowed_paths", [])]

    def max_changed_files(self, project_id: str | None) -> int:
        project = self.get(project_id) if project_id else None
        return int((project or {}).get("max_changed_files", 100))

    def max_diff_bytes(self, project_id: str | None) -> int:
        project = self.get(project_id) if project_id else None
        return int((project or {}).get("max_diff_bytes", 500_000))
