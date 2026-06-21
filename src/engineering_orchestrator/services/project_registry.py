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
