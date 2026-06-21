from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException

from engineering_orchestrator.models import (
    ApprovalDecisionRequest,
    ContinueTaskRequest,
    CreateTaskRequest,
    CreateTaskResponse,
    RouteDecision,
    Task,
)
from engineering_orchestrator.services.approval_service import ApprovalService
from engineering_orchestrator.services.artifact_store import ArtifactStore, slugify
from engineering_orchestrator.services.event_service import EventService
from engineering_orchestrator.services.executor_service import ExecutorService
from engineering_orchestrator.services.git_service import GitService
from engineering_orchestrator.services.planning_service import PlanningService
from engineering_orchestrator.services.project_registry import ProjectRegistry
from engineering_orchestrator.services.review_service import ReviewService
from engineering_orchestrator.services.task_store import TaskStore, utc_now
from engineering_orchestrator.services.validation_service import ValidationService
from engineering_orchestrator.services.workflow_registry import WorkflowRegistry
from engineering_orchestrator.settings import Settings, load_settings


PRE_EXECUTION_GATE_ORDER = ["spec", "config_change", "migration", "security_change", "deploy_prep"]
PRE_EXECUTION_GATE_STATUS = {
    "spec": "awaiting_spec_approval",
    "config_change": "awaiting_config_approval",
    "migration": "awaiting_migration_approval",
    "security_change": "awaiting_security_approval",
    "deploy_prep": "awaiting_deploy_approval",
}


class TaskRouterProtocol(Protocol):
    def route(self, message: str) -> Any:
        pass


class Orchestrator:
    def __init__(self, settings: Settings, task_router: TaskRouterProtocol | None = None):
        self.settings = settings
        self.task_store = TaskStore(settings.sqlite_path)
        self.artifact_store = ArtifactStore(settings.artifacts_root, settings.task_folder_template)
        self.event_service = EventService(self.task_store, self.artifact_store)
        self.approval_service = ApprovalService(self.task_store, self.artifact_store)
        self.projects = ProjectRegistry(settings.projects_path)
        self.workflows = WorkflowRegistry(settings.workflows_path)
        self.executor_service = ExecutorService(settings, self.artifact_store.root_path)
        self.executor = self.executor_service.get(settings.default_executor)
        self.git_service = GitService()
        self.planning_service = PlanningService(
            settings.planner_provider,
            codex_bin=settings.codex_bin,
            model=settings.planner_model or settings.codex_model,
            timeout_seconds=settings.planner_timeout_seconds,
        )
        self.validation_service = ValidationService()
        self.review_service = ReviewService()
        self.task_router = task_router

    def create_task(self, request: CreateTaskRequest) -> CreateTaskResponse:
        task = self.task_store.create_task(request.message, request.source, request.user_id, self.settings.task_id_prefix)
        task.artifacts_dir = self.artifact_store.create_task_folder(task, request.message)
        self.task_store.update_task(task)
        self._add_event(task, "task_created", {"source": request.source})
        self._write_index(task)

        route = self._route_task(task)
        task = self.task_store.get_task(task.id)
        if route.workflow_id in {None, "clarify"}:
            task.status = "awaiting_clarification"
            self.task_store.update_task(task)
            self._add_event(task, "awaiting_clarification", {"warnings": route.warnings})
            self._write_index(task, "Clarification is required before planning.")
            return self._create_response(task, None)

        self._collect_context(task)
        approval = self._create_plan(task)
        task = self.task_store.get_task(task.id)
        return self._create_response(task, approval.gate)

    def get_task(self, task_id: str) -> Task:
        return self.task_store.get_task(task_id)

    def list_artifacts(self, task_id: str):
        return self.task_store.list_artifacts(task_id)

    def read_artifact(self, task_id: str, kind: str, version: int | None = None) -> str:
        artifact = self.task_store.get_artifact(task_id, kind, version)
        if artifact is None:
            raise KeyError(f"Artifact not found: {kind}")
        return self.artifact_store.read_text(artifact)

    def decide_approval(self, task_id: str, gate: str, request: ApprovalDecisionRequest) -> Task:
        task = self.task_store.get_task(task_id)
        approval = self.task_store.get_pending_approval(task_id, gate)
        if approval is None:
            raise KeyError(f"No pending approval for gate: {gate}")

        changed = self.approval_service.refresh_artifact_hashes(approval)
        if changed:
            self._add_event(task, "artifact_modified_externally", {"artifact_ids": changed, "gate": gate})

        if request.decision == "reject":
            self.task_store.resolve_approval(approval.id, "rejected", request.comment)
            task.status = "plan_rejected" if gate == "plan" else "changes_requested"
            self.task_store.update_task(task)
            self._add_event(task, f"{gate}_approval_rejected", {"comment": request.comment})
            self._write_index(task, f"Gate `{gate}` was rejected.")
            return self.task_store.get_task(task_id)

        self.task_store.resolve_approval(approval.id, "approved", request.comment)
        self._add_event(task, f"{gate}_approval_approved", {"comment": request.comment})
        if gate == "plan" or gate in PRE_EXECUTION_GATE_ORDER:
            return self._advance_after_pre_execution_approval(task_id)
        if gate == "diff":
            return self._advance_after_diff_approval(task_id)
        if gate == "commit":
            return self._commit_and_close(task_id)
        return self.task_store.get_task(task_id)

    def continue_task(self, task_id: str, request: ContinueTaskRequest) -> Task:
        task = self.task_store.get_task(task_id)
        task.status = "changes_requested"
        self.task_store.update_task(task)
        self._add_event(task, "user_message_added", {"message": request.message})
        self._write_index(task, "Changes were requested by the user.")
        return self.task_store.get_task(task_id)

    def _route_task(self, task: Task) -> RouteDecision:
        task.status = "routing"
        self.task_store.update_task(task)

        route_payload: dict[str, Any] | None = None
        if self.task_router is not None:
            external_route = self.task_router.route(task.user_message)
            route_payload = self._model_dump(external_route)
            route = self._normalize_route_decision(route_payload)
        else:
            route = self._mock_route_task(task)
            route_payload = route.model_dump()

        task.project_id = route.project_id
        task.project_name = route.project_name
        task.project_path = route.project_path
        task.workflow_id = route.workflow_id
        task.workflow_name = route.workflow_name
        task.risk_level = route.risk_level
        task.route_decision = route_payload
        task.status = "routed" if route.workflow_id not in {None, "clarify"} else "awaiting_clarification"
        self.task_store.update_task(task)
        task = self._rename_artifact_folder_for_route(self.task_store.get_task(task.id))

        artifact = self.artifact_store.write_markdown(task, "route_decision", "Route decision", self._route_markdown(task, route))
        self.task_store.add_artifact(artifact)
        self._add_event(task, "task_routed", route.model_dump())
        self._write_index(self.task_store.get_task(task.id))
        return route

    def _mock_route_task(self, task: Task) -> RouteDecision:
        project = self.projects.find_for_message(task.user_message)
        intent, task_kind, complexity = self._classify(task.user_message)
        workflow = self.workflows.select(intent, task_kind, complexity)

        risk_flags = []
        message_lower = task.user_message.lower()
        for area in (project or {}).get("risky_areas", []):
            if str(area).lower() in message_lower:
                risk_flags.append(str(area))
        if task_kind in {"configuration_change", "dependency_change", "security_change"}:
            risk_flags.append(task_kind)
        risk_level = "high" if risk_flags or complexity in {"complex", "epic"} else "medium"

        return RouteDecision(
            normalized_task=task.user_message.strip(),
            intent=intent,
            task_kind=task_kind,
            complexity=complexity,
            project_id=(project or {}).get("id"),
            project_name=(project or {}).get("name"),
            project_path=(project or {}).get("path"),
            workflow_id=(workflow or {}).get("id"),
            workflow_name=(workflow or {}).get("name"),
            risk_level=risk_level,
            risk_flags=risk_flags,
            approval_gates=(workflow or {}).get("approval_gates", []),
            warnings=[] if project and workflow else ["Project or workflow could not be confidently selected."],
            rationale="Mock router selected project by aliases and workflow by intent/task kind/complexity.",
            requires_spec=bool((workflow or {}).get("requires_spec", False)),
        )

    def _normalize_route_decision(self, route_payload: dict[str, Any]) -> RouteDecision:
        return RouteDecision(
            normalized_task=str(route_payload.get("normalized_task") or "").strip(),
            intent=str(route_payload.get("intent") or "unknown"),
            task_kind=str(route_payload.get("task_kind") or "unknown"),
            complexity=str(route_payload.get("complexity") or "simple"),
            project_id=route_payload.get("project_id"),
            project_name=route_payload.get("project_name"),
            project_path=route_payload.get("project_path"),
            workflow_id=route_payload.get("workflow_id"),
            workflow_name=route_payload.get("workflow_name"),
            risk_level=str(route_payload.get("risk_level") or "medium"),
            risk_flags=list(route_payload.get("risk_flags") or []),
            approval_gates=list(route_payload.get("approval_gates") or []),
            warnings=list(route_payload.get("warnings") or []),
            rationale=str(route_payload.get("rationale") or "Task routed by the configured internal router."),
            requires_spec=bool(route_payload.get("requires_spec", False)),
        )

    def _model_dump(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, dict):
            return value
        raise TypeError(f"Unsupported route decision type: {type(value)!r}")

    def _classify(self, message: str) -> tuple[str, str, str]:
        text = message.lower()
        if text.strip().endswith("?") or any(word in text for word in ["how ", "what ", "why "]):
            return "question", "question", "simple"
        if any(word in text for word in ["migration", "deploy", "architecture", "security"]):
            return "code_change", "security_change" if "security" in text else "migration", "complex"
        if any(word in text for word in ["config", "configuration", "dependency", "setting"]):
            return "code_change", "configuration_change", "medium"
        if any(word in text for word in ["refactor", "cleanup"]):
            return "code_change", "refactor", "medium"
        if any(word in text for word in ["test", "pytest"]):
            return "code_change", "test_update", "simple"
        return "code_change", "bugfix", "simple"

    def _collect_context(self, task: Task) -> None:
        content = f"""# Context

## Project

- ID: `{task.project_id}`
- Name: `{task.project_name}`
- Path: `{task.project_path}`

## Workflow

- ID: `{task.workflow_id}`
- Name: `{task.workflow_name}`
- Risk: `{task.risk_level}`

## Assumptions

- MVP context collection uses route metadata only.
- Source files are not inspected before plan approval.
- Execution after approval uses the configured executor: `{self.settings.default_executor}`.
"""
        artifact = self.artifact_store.write_markdown(task, "context_summary", "Context summary", content)
        self.task_store.add_artifact(artifact)
        self._add_event(task, "context_collected", {"mode": "route_metadata_only"})

    def _create_plan(self, task: Task):
        task.status = "planning"
        self.task_store.update_task(task)
        route = RouteDecision(**(task.route_decision or {}))
        context_artifact = self.task_store.get_artifact(task.id, "context_summary")
        context_markdown = self.artifact_store.read_text(context_artifact) if context_artifact else ""
        draft = self.planning_service.write_plan(task, route, context_markdown)
        artifacts = []

        if route.requires_spec and draft.spec_markdown.strip():
            artifacts.append(
                self.artifact_store.write_markdown(task, "spec", "Specification v1", draft.spec_markdown, version=1)
            )
        artifacts.append(self.artifact_store.write_markdown(task, "todo", "Todo v1", draft.todo_markdown, version=1))
        artifacts.append(self.artifact_store.write_markdown(task, "test_plan", "Test plan v1", draft.test_plan_markdown, version=1))
        artifacts.append(
            self.artifact_store.write_markdown(task, "approval_request", "Plan approval request v1", draft.approval_markdown, version=1)
        )
        for artifact in artifacts:
            self.task_store.add_artifact(artifact)

        approval = self.task_store.create_approval(
            task.id,
            "plan",
            [artifact.id for artifact in artifacts],
            {"approves": ["worktree creation when needed", "configured executor run", "validation", "review report"]},
        )
        task.status = "awaiting_plan_approval"
        self.task_store.update_task(task)
        self._add_event(
            task,
            "plan_approval_requested",
            {"approval_id": approval.id, "planner_provider": self.settings.planner_provider, "planning_notes": draft.planning_notes},
        )
        self._write_index(self.task_store.get_task(task.id), "Pending approval gate: `plan`.")
        return approval

    def _advance_after_pre_execution_approval(self, task_id: str) -> Task:
        task = self.task_store.get_task(task_id)
        next_gate = self._next_pre_execution_gate(task)
        if next_gate is not None:
            return self._request_pre_execution_approval(task, next_gate)
        return self._run_execution(task_id)

    def _next_pre_execution_gate(self, task: Task) -> str | None:
        route_payload = task.route_decision or {}
        approval_gates = list(route_payload.get("approval_gates") or [])
        approvals = self.task_store.list_approvals(task.id)
        approved_gates = {approval.gate for approval in approvals if approval.status == "approved"}

        for gate in PRE_EXECUTION_GATE_ORDER:
            if gate in approval_gates and gate not in approved_gates:
                return gate
        return None

    def _request_pre_execution_approval(self, task: Task, gate: str) -> Task:
        pending = self.task_store.get_pending_approval(task.id, gate)
        if pending is None:
            artifacts = [
                artifact
                for artifact in self.task_store.list_artifacts(task.id)
                if artifact.kind not in {"task_index", "events"}
            ]
            pending = self.task_store.create_approval(
                task.id,
                gate,
                [artifact.id for artifact in artifacts],
                {"approves": [f"{gate} changes before execution"]},
            )
            self._add_event(task, f"{gate}_approval_requested", {"approval_id": pending.id})

        task.status = PRE_EXECUTION_GATE_STATUS.get(gate, "awaiting_plan_approval")
        self.task_store.update_task(task)
        self._write_index(self.task_store.get_task(task.id), f"Pending approval gate: `{gate}`.")
        return self.task_store.get_task(task.id)

    def _run_execution(self, task_id: str) -> Task:
        task = self.task_store.get_task(task_id)
        task.status = "approved_for_execution"
        self.task_store.update_task(task)
        self._add_event(task, "approved_for_execution", {})

        if self.settings.default_executor == "codex":
            task = self._prepare_worktree(task)

        task.status = "executing"
        self.task_store.update_task(task)
        result = self.executor.execute(task, self.task_store.list_artifacts(task.id))
        if task.worktree_path:
            try:
                result.changed_files = self.git_service.changed_files(Path(task.worktree_path))
            except Exception as exc:
                result.logs = (result.logs + "\n\n" if result.logs else "") + f"Could not read git changed files: {exc}"
        execution = self.artifact_store.write_markdown(
            task,
            "execution_log",
            "Execution log",
            self._execution_markdown(task, result),
        )
        self.task_store.add_artifact(execution)
        self._add_event(task, "execution_completed", result.model_dump())

        task.status = "validating"
        self.task_store.update_task(task)
        validation = self.artifact_store.write_markdown(
            task,
            "validation_report",
            "Validation report",
            f"# Validation\n\n{self.validation_service.mock_report() if self.settings.default_executor == 'mock' else self._real_validation_report(task, result)}",
        )
        self.task_store.add_artifact(validation)
        self._add_event(task, "validation_completed", {"status": "recorded", "mode": self.settings.default_executor})

        task.status = "reviewing"
        self.task_store.update_task(task)
        review = self.artifact_store.write_markdown(task, "review_report", "Review report", self._review_markdown(result))
        diff_patch = None
        diff_stat = "No source files were modified."
        if task.worktree_path:
            try:
                diff_stat = self.git_service.diff_stat(Path(task.worktree_path)).strip() or diff_stat
                diff_text = self.git_service.diff_patch(Path(task.worktree_path))
                if diff_text.strip():
                    diff_patch = self.artifact_store.write_markdown(
                        task,
                        "diff_patch",
                        "Diff patch",
                        diff_text,
                        filename="10-diff.patch",
                        include_frontmatter=False,
                    )
                    self.task_store.add_artifact(diff_patch)
            except Exception as exc:
                diff_stat = f"Could not collect git diff: {exc}"
        diff_summary = self.artifact_store.write_markdown(
            task,
            "diff_summary",
            "Diff summary",
            f"# Diff summary\n\nExecutor: `{self.settings.default_executor}`\n\nStatus: `{result.status}`\n\n## Changed files\n\n{self._bullet_list(result.changed_files)}\n\n## Diff stat\n\n```text\n{diff_stat}\n```",
        )
        self.task_store.add_artifact(review)
        self.task_store.add_artifact(diff_summary)

        approval_artifacts = [validation.id, review.id, diff_summary.id]
        if diff_patch is not None:
            approval_artifacts.append(diff_patch.id)
        approval = self.task_store.create_approval(task.id, "diff", approval_artifacts, {"approves": ["commit gate", "close task"]})
        task.status = "awaiting_diff_approval"
        self.task_store.update_task(task)
        self._add_event(task, "diff_approval_requested", {"approval_id": approval.id})
        self._write_index(self.task_store.get_task(task.id), "Pending approval gate: `diff`.")
        return self.task_store.get_task(task.id)

    def _advance_after_diff_approval(self, task_id: str) -> Task:
        task = self.task_store.get_task(task_id)
        route_payload = task.route_decision or {}
        approval_gates = list(route_payload.get("approval_gates") or [])
        if self.settings.require_commit_approval and "commit" in approval_gates:
            return self._request_commit_approval(task)
        return self._commit_and_close(task_id)

    def _request_commit_approval(self, task: Task) -> Task:
        pending = self.task_store.get_pending_approval(task.id, "commit")
        commit_message = self._commit_message(task)
        commit_artifact = self.task_store.get_artifact(task.id, "commit_message")
        if commit_artifact is None:
            commit_artifact = self.artifact_store.write_markdown(
                task,
                "commit_message",
                "Commit message",
                f"# Commit message\n\n```text\n{commit_message}\n```\n",
            )
            self.task_store.add_artifact(commit_artifact)

        if pending is None:
            pending = self.task_store.create_approval(
                task.id,
                "commit",
                [commit_artifact.id],
                {"approves": ["git commit in task worktree"], "commit_message": commit_message},
            )
            self._add_event(task, "commit_approval_requested", {"approval_id": pending.id})

        task.status = "awaiting_commit_approval"
        self.task_store.update_task(task)
        self._write_index(self.task_store.get_task(task.id), "Pending approval gate: `commit`.")
        return self.task_store.get_task(task.id)

    def _prepare_worktree(self, task: Task) -> Task:
        if not task.project_path:
            raise RuntimeError("Cannot run Codex executor: task has no project_path.")
        project_path = Path(task.project_path)
        if not self.git_service.is_repository(project_path):
            raise RuntimeError(f"Cannot run Codex executor: project path is not a git repository: {project_path}")

        task.status = "preparing_worktree"
        task.branch_name = self.settings.branch_template.format(task_id=task.id, slug=slugify(task.user_message))
        self.task_store.update_task(task)

        worktree_path = self.git_service.create_worktree(
            project_path,
            self.settings.worktrees_root,
            task.id,
            task.branch_name,
        )
        task.worktree_path = str(worktree_path)
        self.task_store.update_task(task)
        self._add_event(task, "worktree_created", {"path": task.worktree_path, "branch": task.branch_name})
        return task

    def _execution_markdown(self, task: Task, result) -> str:
        return f"""# Execution

Executor: `{self.settings.default_executor}`
Status: `{result.status}`

## Worktree

`{task.worktree_path or "not created"}`

## Summary

{result.summary}

## Changed files

{self._bullet_list(result.changed_files)}

## Logs

```text
{result.logs or "No logs captured."}
```
"""

    def _real_validation_report(self, task: Task, result) -> str:
        if result.status != "success":
            return f"Execution status is `{result.status}`. Review execution logs before continuing."
        if not task.worktree_path:
            return "No worktree was created; validation commands were not run."
        return (
            "Real executor finished. Automated validation command execution is not wired yet.\n\n"
            "Review the execution logs, changed files, and diff before approving."
        )

    def _review_markdown(self, result) -> str:
        return f"""# Review

Executor: `{self.settings.default_executor}`
Status: `{result.status}`

## Changed files

{self._bullet_list(result.changed_files)}

## Summary

{result.summary}
"""

    def _commit_and_close(self, task_id: str) -> Task:
        task = self.task_store.get_task(task_id)
        task.status = "approved_for_commit"
        self.task_store.update_task(task)
        commit_hash = None
        commit_summary = "Commit skipped: no worktree is attached to this task."
        if task.worktree_path:
            task.status = "committing"
            self.task_store.update_task(task)
            try:
                commit_hash = self.git_service.commit(Path(task.worktree_path), self._commit_message(task))
                commit_summary = f"Commit created in task worktree: `{commit_hash}`."
                self._add_event(task, "commit_created", {"commit_hash": commit_hash, "worktree_path": task.worktree_path})
            except Exception as exc:
                task.status = "failed"
                self.task_store.update_task(task)
                commit_summary = f"Commit failed: {exc}"
                self._add_event(task, "commit_failed", {"error": str(exc)})

        commit = self.artifact_store.write_markdown(
            task,
            "commit_result",
            "Commit result",
            f"# Commit result\n\n{commit_summary}\n",
        )
        final = self.artifact_store.write_markdown(
            task,
            "final_report",
            "Final report",
            f"# Final report\n\nTask closed after commit gate.\n\nCommit: `{commit_hash or 'none'}`\n",
        )
        self.task_store.add_artifact(commit)
        self.task_store.add_artifact(final)
        if task.status != "failed":
            task.status = "closed"
            task.closed_at = utc_now()
            self.task_store.update_task(task)
            self._add_event(task, "task_closed", {"reason": "lifecycle_complete", "commit_hash": commit_hash})
            self._write_index(self.task_store.get_task(task.id), "Task is closed.")
        else:
            self._write_index(self.task_store.get_task(task.id), "Commit failed.")
        return self.task_store.get_task(task.id)

    def _commit_message(self, task: Task) -> str:
        slug = slugify(task.user_message, fallback="task").replace("-", " ")
        return f"{task.id}: {slug[:72]}".strip()

    def _add_event(self, task: Task, event_type: str, payload: dict | None = None) -> None:
        current = self.task_store.get_task(task.id)
        self.event_service.add(current, event_type, payload or {})

    def _rename_artifact_folder_for_route(self, task: Task) -> Task:
        if not task.artifacts_dir or not task.project_id:
            return task

        old_dir = task.artifacts_dir
        new_dir = self.settings.task_folder_template.format(
            task_id=task.id,
            project_id=task.project_id,
            slug=slugify(task.user_message),
        ).strip()
        if new_dir == old_dir:
            return task

        old_path = self.artifact_store.root_path / old_dir
        new_path = self.artifact_store.root_path / new_dir
        if old_path.exists() and not new_path.exists():
            old_path.rename(new_path)
        else:
            new_path.mkdir(parents=True, exist_ok=True)

        for artifact in self.task_store.list_artifacts(task.id):
            path = Path(artifact.relative_path)
            if path.parts and path.parts[0] == old_dir:
                artifact.relative_path = Path(new_dir, *path.parts[1:]).as_posix()
                self.task_store.update_artifact(artifact)

        task.artifacts_dir = new_dir
        self.task_store.update_task(task)
        return task

    def _write_index(self, task: Task, approval_summary: str = "No pending approval.") -> None:
        artifacts = [artifact for artifact in self.task_store.list_artifacts(task.id) if artifact.kind != "task_index"]
        artifact = self.artifact_store.update_task_index(task, artifacts, approval_summary)
        previous = self.task_store.get_artifact(task.id, "task_index")
        if previous is not None:
            artifact.id = previous.id
            artifact.created_at = previous.created_at
        self.task_store.add_artifact(artifact)

    def _create_response(self, task: Task, gate: str | None) -> CreateTaskResponse:
        return CreateTaskResponse(
            task_id=task.id,
            status=task.status,
            project_id=task.project_id,
            workflow_id=task.workflow_id,
            artifacts_dir=task.artifacts_dir,
            current_approval_gate=gate,
        )

    def _route_markdown(self, task: Task, route: RouteDecision) -> str:
        return f"""# Route decision

## Original request

> {task.user_message}

## Normalized task

{route.normalized_task}

## Decision

- Project: `{route.project_id}`
- Workflow: `{route.workflow_id}`
- Intent: `{route.intent}`
- Task kind: `{route.task_kind}`
- Complexity: `{route.complexity}`
- Risk: `{route.risk_level}`
- Approval gates: `{", ".join(route.approval_gates) or "none"}`

## Risk flags

{self._bullet_list(route.risk_flags)}

## Warnings

{self._bullet_list(route.warnings)}

## Rationale

{route.rationale}
"""

    def _spec_markdown(self, task: Task, route: RouteDecision) -> str:
        return f"""# Specification

## Goal

Resolve the requested task for `{task.project_id}`: {task.user_message}

## Non-goals

- Production deploy.
- Secret changes.
- Destructive database migrations.
- Real source modification before plan approval.

## Affected areas

- Project: `{task.project_id}`
- Workflow: `{task.workflow_id}`
- Risk flags: `{", ".join(route.risk_flags) or "none"}`

## Acceptance criteria

- Plan is approved before execution.
- Configured execution produces execution, validation, and review artifacts.
- Diff approval is requested before closing.

## Risks

{self._bullet_list(route.risk_flags or ["No specific risk flags detected by mock router."])}

## Approval gates

{self._bullet_list(route.approval_gates)}
"""

    def _todo_markdown(self, task: Task) -> str:
        return f"""# Todo

- [ ] Collect relevant context for `{task.project_id}`.
- [ ] Identify affected files.
- [ ] Implement approved change.
- [ ] Add or update tests.
- [ ] Run validation.
- [ ] Prepare review report.
"""

    def _test_plan_markdown(self, task: Task) -> str:
        return f"""# Test plan

## Automated checks

- Use configured project test commands when real execution is enabled.
- MVP mock validation records a pass without running project commands.

## Manual checks

- Open generated Markdown artifacts in Obsidian.
- Confirm approval gates match the selected workflow.

## Regression expectations

- The original request should be covered by implementation notes before real execution is enabled.

## Risk-specific tests

- Risk level: `{task.risk_level}`
- Add focused tests for risky areas before enabling real commits.
"""

    def _approval_plan_markdown(self) -> str:
        return """# Approval request

Approving this plan allows the agent to:

- Create a task branch/worktree when real git execution is enabled.
- Modify source/test files according to the plan when real execution is enabled.
- Run configured validation commands.
- Produce a diff for review.

This approval does not allow:

- Direct production deploy.
- Secret changes.
- Destructive database migrations.
- Commit without final diff approval.
"""

    def _bullet_list(self, values: list[str]) -> str:
        if not values:
            return "- None."
        return "\n".join(f"- {value}" for value in values)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="engineering_orchestrator", version="0.1.0")
    orchestrator = Orchestrator(settings or load_settings())
    app.state.orchestrator = orchestrator

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/tasks", response_model=CreateTaskResponse)
    def create_task(request: CreateTaskRequest):
        return orchestrator.create_task(request)

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str):
        try:
            return orchestrator.get_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/artifacts")
    def list_artifacts(task_id: str):
        try:
            orchestrator.get_task(task_id)
            return orchestrator.list_artifacts(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/artifacts/{kind}")
    def read_artifact(task_id: str, kind: str, version: int | None = None):
        try:
            return {"content": orchestrator.read_artifact(task_id, kind, version)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/approvals/{gate}")
    def decide_approval(task_id: str, gate: str, request: ApprovalDecisionRequest):
        try:
            return orchestrator.decide_approval(task_id, gate, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/messages")
    def continue_task(task_id: str, request: ContinueTaskRequest):
        try:
            return orchestrator.continue_task(task_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = create_app()
