from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from task_router.models import ProjectConfig, RouterConfig, ToolConfig, WorkflowConfig


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_router_config(projects_path: str | Path, workflows_path: str | Path) -> RouterConfig:
    projects_data = _load_yaml(Path(projects_path))
    workflows_data = _load_yaml(Path(workflows_path))

    tools = {item["id"]: ToolConfig(**item) for item in projects_data.get("tools", [])}
    projects = {item["id"]: ProjectConfig(**item) for item in projects_data.get("projects", [])}
    workflows = {item["id"]: WorkflowConfig(**item) for item in workflows_data.get("workflows", [])}

    _validate_references(tools, projects, workflows)
    return RouterConfig(tools=tools, projects=projects, workflows=workflows)


def _validate_references(
    tools: dict[str, ToolConfig],
    projects: dict[str, ProjectConfig],
    workflows: dict[str, WorkflowConfig],
) -> None:
    missing: list[str] = []

    for project in projects.values():
        for tool_id in project.tools:
            if tool_id not in tools:
                missing.append(f"project {project.id} references missing tool {tool_id}")

    for workflow in workflows.values():
        for project_id in workflow.project_ids:
            if project_id != "*" and project_id not in projects:
                missing.append(f"workflow {workflow.id} references missing project {project_id}")
        for tool_id in workflow.required_tools:
            if tool_id not in tools:
                missing.append(f"workflow {workflow.id} references missing tool {tool_id}")
        if not workflow.complexity:
            missing.append(f"workflow {workflow.id} must define at least one complexity value")
        if not workflow.steps and workflow.id not in {"clarify", "question_only"}:
            missing.append(f"workflow {workflow.id} must define at least one step")

    if not workflows:
        missing.append("workflows.yml must define at least one workflow")

    if missing:
        raise ValueError("Invalid router config:\n- " + "\n- ".join(missing))
