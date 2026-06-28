from __future__ import annotations

from pathlib import Path
from typing import Any

from engineering_orchestrator.harness.skills import SkillsService
from engineering_orchestrator.harness.working_memory import WorkingMemory
from engineering_orchestrator.models import Task
from engineering_orchestrator.services.project_registry import ProjectRegistry
from engineering_orchestrator.services.task_store import TaskStore
from engineering_orchestrator.services.workflow_registry import WorkflowRegistry


class ContextBuilder:
    def __init__(
        self,
        task_store: TaskStore,
        projects: ProjectRegistry,
        workflows: WorkflowRegistry,
        skills: SkillsService | None = None,
        base_dir: str | Path | None = None,
        tool_policy: dict[str, Any] | None = None,
        stop_conditions: dict[str, Any] | None = None,
    ):
        self.task_store = task_store
        self.projects = projects
        self.workflows = workflows
        self.skills = skills or SkillsService()
        self.base_dir = Path(base_dir or ".").resolve()
        self.tool_policy = tool_policy or {
            "do_not_commit_without_approval": True,
            "do_not_deploy": True,
            "include_untracked_files_in_review": True,
        }
        self.stop_conditions = stop_conditions or {}

    def build(self, task: Task) -> WorkingMemory:
        project = self.projects.get(task.project_id or "") or {}
        workflow = self.workflows.get(task.workflow_id or "") or {}
        artifacts = [
            {
                "id": artifact.id,
                "kind": artifact.kind,
                "version": artifact.version,
                "title": artifact.title,
                "relative_path": artifact.relative_path,
            }
            for artifact in self.task_store.list_artifacts(task.id)
        ]
        approvals = [
            {"gate": approval.gate, "status": approval.status, "artifact_ids": approval.artifact_ids}
            for approval in self.task_store.list_approvals(task.id)
        ]
        events = [
            {"event_type": event.event_type, "created_at": event.created_at.isoformat(), "payload": event.payload}
            for event in self.task_store.list_events(task.id)
        ]
        approval_gates = list((task.route_decision or {}).get("approval_gates") or workflow.get("approval_gates") or [])
        return WorkingMemory(
            task_id=task.id,
            user_prompt=task.user_message,
            route_decision=task.route_decision,
            workflow_policy=workflow,
            project_profile=project,
            procedural_instructions=self.skills.list_instructions(self.base_dir),
            semantic_facts=[
                {"id": "approvals", "value": approvals},
                {"id": "events", "value": events},
            ],
            relevant_files=[],
            current_artifacts=artifacts,
            tool_policy=self.tool_policy,
            approval_gates=approval_gates,
            stop_conditions=self.stop_conditions,
        )
