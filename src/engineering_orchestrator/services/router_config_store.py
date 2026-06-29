from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import yaml

from task_router.config_loader import load_router_config


class RouterConfigStore:
    def __init__(self, projects_path: str | Path, workflows_path: str | Path):
        self.projects_path = Path(projects_path)
        self.workflows_path = Path(workflows_path)

    def read(self) -> dict[str, Any]:
        projects_doc = self._load_mapping(self.projects_path, {"tools": [], "projects": []})
        workflows_doc = self._load_mapping(self.workflows_path, {"workflows": []})
        return {
            "projects_path": str(self.projects_path),
            "workflows_path": str(self.workflows_path),
            "tools": list(projects_doc.get("tools") or []),
            "projects": list(projects_doc.get("projects") or []),
            "workflows": list(workflows_doc.get("workflows") or []),
        }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        projects_doc = self._load_mapping(self.projects_path, {"tools": [], "projects": []})
        workflows_doc = self._load_mapping(self.workflows_path, {"workflows": []})

        next_projects_doc = dict(projects_doc)
        next_workflows_doc = dict(workflows_doc)
        next_projects_doc["tools"] = self._section(payload, "tools")
        next_projects_doc["projects"] = self._section(payload, "projects")
        next_workflows_doc["workflows"] = self._section(payload, "workflows")

        self._validate_unique_ids(next_projects_doc["tools"], "tools")
        self._validate_unique_ids(next_projects_doc["projects"], "projects")
        self._validate_unique_ids(next_workflows_doc["workflows"], "workflows")
        self._validate_router_config(next_projects_doc, next_workflows_doc)

        self._write_yaml(self.projects_path, next_projects_doc)
        self._write_yaml(self.workflows_path, next_workflows_doc)
        return self.read()

    def _section(self, payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value = payload.get(key)
        if not isinstance(value, list):
            raise ValueError(f"`{key}` must be a list.")
        result: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(f"`{key}[{index}]` must be an object.")
            result.append(dict(item))
        return result

    def _validate_unique_ids(self, items: list[dict[str, Any]], section: str) -> None:
        seen: set[str] = set()
        for index, item in enumerate(items):
            raw_id = item.get("id")
            if not raw_id:
                raise ValueError(f"`{section}[{index}].id` is required.")
            item_id = str(raw_id)
            if item_id in seen:
                raise ValueError(f"`{section}` contains duplicate id `{item_id}`.")
            seen.add(item_id)

    def _validate_router_config(self, projects_doc: dict[str, Any], workflows_doc: dict[str, Any]) -> None:
        with tempfile.TemporaryDirectory(prefix="tasker-router-config-") as tmp_dir:
            tmp_root = Path(tmp_dir)
            tmp_projects = tmp_root / "projects.yml"
            tmp_workflows = tmp_root / "workflows.yml"
            self._write_yaml(tmp_projects, projects_doc)
            self._write_yaml(tmp_workflows, workflows_doc)
            load_router_config(tmp_projects, tmp_workflows)

    def _load_mapping(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return dict(default)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML mapping.")
        return data

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        tmp_path.replace(path)
