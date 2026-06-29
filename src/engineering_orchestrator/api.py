from __future__ import annotations

import json
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from engineering_orchestrator.harness import ContextBuilder, PromptBuilder
from engineering_orchestrator.loop import Evaluator, LoopPolicy, Observer, RepairPlanner
from engineering_orchestrator.models import (
    ApprovalDecisionRequest,
    CancelTaskRequest,
    ContinueTaskRequest,
    CreateTaskRequest,
    CreateTaskResponse,
    JobAcceptedResponse,
    RouteDecision,
    Task,
)
from engineering_orchestrator.services.approval_service import ApprovalService
from engineering_orchestrator.services.artifact_store import ArtifactStore, slugify, slugify_short
from engineering_orchestrator.services.event_service import EventService
from engineering_orchestrator.services.executor_service import ExecutorService
from engineering_orchestrator.services.git_service import GitService
from engineering_orchestrator.services.job_runner import JobRunner
from engineering_orchestrator.services.planning_service import PlanningService
from engineering_orchestrator.services.project_registry import ProjectRegistry
from engineering_orchestrator.services.review_service import ReviewService
from engineering_orchestrator.services.task_store import TaskStore, utc_now
from engineering_orchestrator.services.validation_service import ValidationService
from engineering_orchestrator.services.workflow_registry import WorkflowRegistry
from engineering_orchestrator.settings import Settings, load_settings
from engineering_orchestrator.ui import register_ui_routes


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
        self.job_runner = JobRunner(self.task_store)
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
        self.prompt_builder = PromptBuilder()
        self.context_builder = ContextBuilder(
            self.task_store,
            self.projects,
            self.workflows,
            base_dir=Path(settings.projects_path).resolve().parent.parent,
            stop_conditions=self._loop_policy().model_dump(),
        )
        self.observer = Observer(self.git_service)
        self.evaluator = Evaluator(self._loop_policy())
        self.repair_planner = RepairPlanner()

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
        if route.workflow_id == "question_only":
            task = self._answer_question_and_close(task.id)
            return self._create_response(task, None)

        approval = self._create_plan(task)
        if approval is None:
            task = self._advance_after_pre_execution_approval(task.id)
            return self._create_response(task, self._pending_gate(task))

        task = self.task_store.get_task(task.id)
        return self._create_response(task, approval.gate)

    def get_task(self, task_id: str) -> Task:
        return self.task_store.get_task(task_id)

    def get_task_payload(self, task_id: str) -> dict[str, Any]:
        task = self.task_store.get_task(task_id)
        payload = task.model_dump(mode="json")
        payload["current_approval_gate"] = self.task_store.get_current_approval_gate(task.id)
        payload["runtime"] = self.runtime_summary()
        payload["latest_job"] = self.latest_job_payload(task.id)
        return payload

    def list_tasks(self, status: str | None = None, project_id: str | None = None, limit: int = 100) -> list[Task]:
        return self.task_store.list_tasks(status, project_id=project_id, limit=limit)  # type: ignore[arg-type]

    def list_tasks_page(
        self,
        status: str | None = None,
        project_id: str | None = None,
        workflow_id: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        tasks, total = self.task_store.list_tasks_page(
            status,  # type: ignore[arg-type]
            project_id=project_id,
            workflow_id=workflow_id,
            q=q,
            limit=limit,
            offset=offset,
        )
        items = []
        for task in tasks:
            item = task.model_dump(mode="json")
            item["current_approval_gate"] = self.task_store.get_current_approval_gate(task.id)
            item["runtime"] = self.runtime_summary()
            item["latest_job"] = self.latest_job_payload(task.id)
            items.append(item)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def list_artifacts(self, task_id: str):
        return self.task_store.list_artifacts(task_id)

    def list_approvals(self, task_id: str):
        self.task_store.get_task(task_id)
        return self.task_store.list_approvals(task_id)

    def list_events(self, task_id: str):
        self.task_store.get_task(task_id)
        return self.task_store.list_events(task_id)

    def get_context(self, task_id: str):
        task = self.task_store.get_task(task_id)
        return self.context_builder.build(task)

    def rebuild_context(self, task_id: str):
        task = self.task_store.get_task(task_id)
        return self._write_working_memory(task)

    def list_runs(self, task_id: str):
        self.task_store.get_task(task_id)
        return self.task_store.list_runs(task_id)

    def list_jobs(self, task_id: str):
        self.task_store.get_task(task_id)
        return self.task_store.list_jobs(task_id)

    def get_job(self, job_id: str):
        return self.task_store.get_job(job_id)

    def latest_job_payload(self, task_id: str) -> dict[str, Any] | None:
        jobs = self.task_store.list_jobs(task_id)
        if not jobs:
            return None
        return jobs[-1].model_dump(mode="json")

    def runtime_summary(self) -> dict[str, Any]:
        return {
            "router": self.settings.router_provider,
            "planner": self.settings.planner_provider,
            "executor": self.settings.default_executor,
            "mode": "dry-run"
            if "mock" in {self.settings.router_provider, self.settings.planner_provider, self.settings.default_executor}
            else "live",
        }

    def get_run(self, run_id: str):
        return self.task_store.get_run(run_id)

    def list_steps(self, run_id: str):
        self.task_store.get_run(run_id)
        return self.task_store.list_steps(run_id)

    def read_artifact(self, task_id: str, kind: str, version: int | None = None) -> str:
        artifact = self.task_store.get_artifact(task_id, kind, version)
        if artifact is None:
            raise KeyError(f"Artifact not found: {kind}")
        return self.artifact_store.read_text(artifact)

    def read_artifact_by_id(self, task_id: str, artifact_id: str) -> dict[str, Any]:
        self.task_store.get_task(task_id)
        artifact = self.task_store.get_artifact_by_id(task_id, artifact_id)
        if artifact is None:
            raise KeyError(f"Artifact not found: {artifact_id}")
        return {"artifact": artifact.model_dump(mode="json"), "content": self.artifact_store.read_text(artifact)}

    def cancel_task(self, task_id: str, request: CancelTaskRequest) -> Task:
        task = self.task_store.get_task(task_id)
        cancelled = self.task_store.cancel_task(task_id, request.comment)
        self._add_event(cancelled, "task_cancelled", {"comment": request.comment})
        self._write_index(self.task_store.get_task(task.id), "Task was cancelled.")
        return self.task_store.get_task(task_id)

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
            if gate == "diff":
                self._create_correction_request(task, gate, request.comment)
                self._add_event(task, "diff_correction_requested", {"comment": request.comment})
                return self._revise_plan(task_id, request.comment or "Diff was rejected; prepare a focused correction plan.")
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
        self._add_event(task, "user_message_added", {"message": request.message})
        if task.status in {"plan_rejected", "changes_requested", "validation_failed"}:
            return self._revise_plan(task_id, request.message)

        task.status = "changes_requested"
        self.task_store.update_task(task)
        self._write_index(task, "Changes were requested by the user.")
        return self.task_store.get_task(task_id)

    def enqueue_continue_task(self, task_id: str, request: ContinueTaskRequest) -> JobAcceptedResponse:
        self.task_store.get_task(task_id)
        job = self.job_runner.enqueue(
            task_id,
            "continue_task",
            lambda: self.continue_task(task_id, request),
        )
        return JobAcceptedResponse(job_id=job.id, task_id=task_id, status=job.status, action=job.action)

    def enqueue_approval_decision(
        self,
        task_id: str,
        gate: str,
        request: ApprovalDecisionRequest,
    ) -> JobAcceptedResponse:
        self.task_store.get_task(task_id)
        job = self.job_runner.enqueue(
            task_id,
            f"approval:{gate}:{request.decision}",
            lambda: self.decide_approval(task_id, gate, request),
        )
        return JobAcceptedResponse(job_id=job.id, task_id=task_id, status=job.status, action=job.action)

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
        self._write_working_memory(task)
        self._add_event(task, "context_collected", {"mode": "route_metadata_only"})

    def _write_working_memory(self, task: Task):
        memory = self.context_builder.build(task)
        markdown = self.prompt_builder.render_memory_markdown(memory)
        markdown_artifact = self.artifact_store.write_markdown(
            task,
            "working_memory",
            "Working memory",
            markdown,
        )
        json_artifact = self.artifact_store.write_json(
            task,
            "working_memory_json",
            "Working memory JSON",
            memory.model_dump(mode="json"),
        )
        self.task_store.add_artifact(markdown_artifact)
        self.task_store.add_artifact(json_artifact)
        return memory

    def _create_plan(self, task: Task, revision_comment: str | None = None):
        task.status = "planning"
        self.task_store.update_task(task)
        route = RouteDecision(**(task.route_decision or {}))
        context_artifact = self.task_store.get_artifact(task.id, "context_summary")
        context_markdown = self.artifact_store.read_text(context_artifact) if context_artifact else ""
        if revision_comment:
            context_markdown = context_markdown.rstrip() + f"\n\n## Latest correction request\n\n{revision_comment}\n"
        draft = self.planning_service.write_plan(task, route, context_markdown)
        artifacts = []
        version = self._next_plan_version(task.id)

        if route.requires_spec and draft.spec_markdown.strip():
            artifacts.append(
                self.artifact_store.write_markdown(task, "spec", f"Specification v{version}", draft.spec_markdown, version=version)
            )
        artifacts.append(self.artifact_store.write_markdown(task, "todo", f"Todo v{version}", draft.todo_markdown, version=version))
        artifacts.append(
            self.artifact_store.write_markdown(task, "test_plan", f"Test plan v{version}", draft.test_plan_markdown, version=version)
        )
        approval_markdown = draft.approval_markdown
        if revision_comment:
            approval_markdown = approval_markdown.rstrip() + f"\n\n## Correction request\n\n{revision_comment}\n"
        artifacts.append(
            self.artifact_store.write_markdown(
                task,
                "approval_request",
                f"Plan approval request v{version}",
                approval_markdown,
                version=version,
            )
        )
        for artifact in artifacts:
            self.task_store.add_artifact(artifact)

        event_payload = {
            "planner_provider": self.settings.planner_provider,
            "planning_notes": draft.planning_notes,
            "plan_version": version,
        }
        if not self.settings.require_plan_approval:
            self._add_event(task, "plan_approval_skipped", event_payload)
            self._write_index(self.task_store.get_task(task.id), "Plan approval is disabled by policy.")
            return None

        approval = self.task_store.create_approval(
            task.id,
            "plan",
            [artifact.id for artifact in artifacts],
            {
                "approves": ["worktree creation when needed", "configured executor run", "validation", "review report"],
                "plan_version": version,
                "revision_comment": revision_comment,
            },
        )
        task.status = "awaiting_plan_approval"
        self.task_store.update_task(task)
        self._add_event(task, "plan_approval_requested", {"approval_id": approval.id, **event_payload})
        self._write_index(self.task_store.get_task(task.id), "Pending approval gate: `plan`.")
        return approval

    def _revise_plan(self, task_id: str, correction: str) -> Task:
        task = self.task_store.get_task(task_id)
        approval = self._create_plan(task, revision_comment=correction)
        self._add_event(task, "plan_revised", {"approval_id": approval.id if approval else None, "correction": correction})
        if approval is None:
            return self._advance_after_pre_execution_approval(task_id)
        self._write_index(self.task_store.get_task(task.id), "Revised plan is pending approval gate: `plan`.")
        return self.task_store.get_task(task_id)

    def _create_correction_request(self, task: Task, gate: str, comment: str | None):
        body = comment.strip() if comment and comment.strip() else "No rejection comment was provided."
        version = self._next_plan_version(task.id)
        markdown = f"""# Correction request

## Rejected gate

`{gate}`

## User comment

{body}

## Required next step

Create a focused v{version} correction plan from this comment. Preserve unrelated files and previous approved scope unless the comment explicitly changes it.
"""
        artifact = self.artifact_store.write_markdown(
            task,
            "correction_request",
            f"Correction request v{version}",
            markdown,
            version=version,
        )
        self.task_store.add_artifact(artifact)
        return artifact

    def _next_plan_version(self, task_id: str) -> int:
        versions = [
            artifact.version or 0
            for artifact in self.task_store.list_artifacts(task_id)
            if artifact.kind in {"spec", "todo", "test_plan", "approval_request"}
        ]
        return max(versions, default=0) + 1

    def _answer_question_and_close(self, task_id: str) -> Task:
        task = self.task_store.get_task(task_id)
        task.status = "closed"
        task.closed_at = utc_now()
        self.task_store.update_task(task)

        answer = self.artifact_store.write_markdown(
            task,
            "answer",
            "Answer",
            self._answer_markdown(task),
        )
        final = self.artifact_store.write_markdown(
            task,
            "final_report",
            "Final report",
            "# Final report\n\nQuestion-only task closed without plan, execution, diff, or commit approval gates.\n",
        )
        self.task_store.add_artifact(answer)
        self.task_store.add_artifact(final)
        self._add_event(task, "question_answered", {"answer_artifact_id": answer.id})
        self._write_index(self.task_store.get_task(task.id), "Task is closed.")
        return self.task_store.get_task(task.id)

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

    def _loop_policy(self) -> LoopPolicy:
        return LoopPolicy(
            max_iterations=self.settings.loop_default_max_iterations,
            max_changed_files=self.settings.loop_default_max_changed_files,
            max_diff_lines=self.settings.loop_default_max_diff_lines,
            repair_on_validation_failure=self.settings.loop_repair_on_validation_failure,
            require_human_on_blocked_path=self.settings.loop_require_human_on_blocked_path,
            require_human_on_config_change=self.settings.loop_require_human_on_config_change,
        )

    def _run_execution(self, task_id: str) -> Task:
        task = self.task_store.get_task(task_id)
        run = self.task_store.create_run(
            task.id,
            "execution",
            executor=self.settings.default_executor,
            model=self.settings.codex_model if self.settings.default_executor == "codex" else None,
        )
        task.status = "approved_for_execution"
        self.task_store.update_task(task)
        self._add_event(task, "approved_for_execution", {"run_id": run.id})

        if self.settings.default_executor == "codex" and not task.worktree_path:
            task = self._prepare_worktree(task)
        if self.settings.default_executor == "codex":
            self._write_executor_policy(task)

        task.status = "executing"
        self.task_store.update_task(task)
        result = self.executor.execute(task, self.task_store.list_artifacts(task.id))
        execution = self.artifact_store.write_markdown(
            task,
            "execution_log",
            "Execution log",
            self._execution_markdown(task, result),
        )
        self.task_store.add_artifact(execution)
        self._write_executor_result_artifacts(task, result, run.id)
        self._add_event(task, "execution_completed", result.model_dump())
        self.task_store.add_step(
            run.id,
            1,
            "execute",
            "passed" if result.status == "success" else "failed",
            input_summary=f"Executor `{self.settings.default_executor}`",
            output_summary=result.summary,
            artifact_ids=[execution.id],
            error=None if result.status == "success" else result.logs,
        )

        if result.status != "success":
            task.status = "prompt_too_large" if "prompt_too_large" in result.summary else "changes_requested"
            self.task_store.update_task(task)
            validation = self.artifact_store.write_markdown(
                task,
                "validation_report",
                "Validation report",
                "# Validation\n\n"
                f"Status: `skipped`\n\nExecution status is `{result.status}`. Review execution logs before continuing.\n",
            )
            self.task_store.add_artifact(validation)
            self.task_store.add_step(
                run.id,
                2,
                "validate",
                "skipped",
                output_summary="Execution did not succeed; validation skipped.",
                artifact_ids=[validation.id],
            )
            evaluation = self.task_store.add_evaluation(
                run.id,
                task.id,
                passed=False,
                status="failed",
                findings=[{"code": "executor_failed", "severity": "error", "message": f"Executor status: {result.status}"}],
            )
            eval_artifact = self.artifact_store.write_markdown(
                task,
                "evaluation_report",
                "Evaluation report",
                self._evaluation_markdown(evaluation),
            )
            self.task_store.add_artifact(eval_artifact)
            self.task_store.add_step(
                run.id,
                3,
                "evaluate",
                "failed",
                output_summary="Executor failed.",
                artifact_ids=[eval_artifact.id],
            )
            self.task_store.finish_run(run.id, "failed", iteration_count=1, stop_reason="executor_failed")
            self._write_run_artifacts(task, run.id)
            self._add_event(task, "validation_skipped", {"reason": "execution_not_successful", "execution_status": result.status})
            self._write_index(self.task_store.get_task(task.id), "Execution failed. Awaiting corrections.")
            return self.task_store.get_task(task.id)

        task.status = "validating"
        self.task_store.update_task(task)
        validation_result = self._run_validation(task)
        validation = self.artifact_store.write_markdown(
            task,
            "validation_report",
            "Validation report",
            self.validation_service.markdown_report(validation_result),
        )
        self.task_store.add_artifact(validation)
        self._write_validation_command_outputs(task, validation_result)
        self._add_event(task, "validation_completed", validation_result.model_dump())
        self.task_store.add_step(
            run.id,
            2,
            "validate",
            "passed" if validation_result.status in {"passed", "skipped"} else "failed",
            output_summary=validation_result.summary,
            artifact_ids=[validation.id],
        )

        diff_patch = None
        diff_stat = "No source files were modified."
        diff_text = ""
        observation = None
        if task.worktree_path:
            try:
                observation = self.observer.observe(task.worktree_path, result, validation_result)
                result.changed_files = observation.changed_files
                diff_stat = observation.diff_stat.strip() or diff_stat
                diff_text = observation.diff_patch
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
                result.logs = (result.logs + "\n\n" if result.logs else "") + diff_stat
        self.task_store.add_step(
            run.id,
            3,
            "observe",
            "passed",
            output_summary=f"{len(result.changed_files)} changed file(s).",
            artifact_ids=[diff_patch.id] if diff_patch is not None else [],
        )

        approved_gates = {approval.gate for approval in self.task_store.list_approvals(task.id) if approval.status == "approved"}
        project = self.projects.get(task.project_id or "") or {}
        workflow = self.workflows.get(task.workflow_id or "") or {}
        if observation is None:
            from engineering_orchestrator.loop.observer import Observation

            observation = Observation(
                executor_result=result,
                validation_result=validation_result,
                changed_files=result.changed_files,
                diff_stat=diff_stat,
                diff_patch=diff_text,
            )
        loop_evaluation = self.evaluator.evaluate(observation, project, workflow, approved_gates)
        evaluation = self.task_store.add_evaluation(
            run.id,
            task.id,
            passed=loop_evaluation.passed,
            status=loop_evaluation.status,
            findings=loop_evaluation.findings,
        )
        eval_artifact = self.artifact_store.write_markdown(
            task,
            "evaluation_report",
            "Evaluation report",
            self._evaluation_markdown(evaluation),
        )
        self.task_store.add_artifact(eval_artifact)
        self.task_store.add_step(
            run.id,
            4,
            "evaluate",
            loop_evaluation.status,
            output_summary=f"Evaluation status: {loop_evaluation.status}",
            artifact_ids=[eval_artifact.id],
        )

        policy_status, policy_markdown = self._evaluate_policy(task, result.changed_files, diff_text, loop_evaluation.findings)
        policy_artifact = self.artifact_store.write_markdown(task, "policy_report", "Policy report", policy_markdown)
        self.task_store.add_artifact(policy_artifact)
        self._add_event(task, "policy_checked", {"status": policy_status})
        if not loop_evaluation.passed:
            if loop_evaluation.status == "repairable":
                repair = self.artifact_store.write_markdown(
                    task,
                    "repair_prompt",
                    "Repair prompt",
                    self.repair_planner.build_prompt(loop_evaluation.findings, validation_result.summary, diff_text),
                )
                self.task_store.add_artifact(repair)
                self.task_store.add_step(
                    run.id,
                    5,
                    "repair",
                    "stopped",
                    output_summary="Repair prompt created; human or future loop iteration required.",
                    artifact_ids=[repair.id],
                )
                task.status = "validation_failed"
                stop_reason = "validation_failed"
            else:
                task.status = "changes_requested"
                stop_reason = loop_evaluation.status
            self.task_store.update_task(task)
            self.task_store.finish_run(run.id, loop_evaluation.status, iteration_count=1, stop_reason=stop_reason)
            self._write_run_artifacts(task, run.id)
            self._write_index(self.task_store.get_task(task.id), "Evaluation did not pass. Awaiting corrections.")
            return self.task_store.get_task(task.id)

        task.status = "reviewing"
        self.task_store.update_task(task)
        review = self.artifact_store.write_markdown(
            task,
            "review_report",
            "Review report",
            self._review_markdown_structured(result, validation_result, evaluation, diff_stat),
        )
        diff_summary = self.artifact_store.write_markdown(
            task,
            "diff_summary",
            "Diff summary",
            f"# Diff summary\n\nExecutor: `{self.settings.default_executor}`\n\nStatus: `{result.status}`\n\n## Changed files\n\n{self._bullet_list(result.changed_files)}\n\n## Diff stat\n\n```text\n{diff_stat}\n```",
        )
        self.task_store.add_artifact(review)
        self.task_store.add_artifact(diff_summary)
        self.task_store.finish_run(run.id, "passed", iteration_count=1, stop_reason="evaluation_passed")
        self._write_run_artifacts(task, run.id)

        approval_artifacts = [validation.id, eval_artifact.id, policy_artifact.id, review.id, diff_summary.id]
        if diff_patch is not None:
            approval_artifacts.append(diff_patch.id)

        reviewed_files = list(result.changed_files)
        diff_payload = {"approves": ["commit gate", "close task"], "reviewed_files": reviewed_files}
        if not self.settings.require_diff_approval:
            self._add_event(task, "diff_approval_skipped", {"artifact_ids": approval_artifacts})
            self._write_index(self.task_store.get_task(task.id), "Diff approval is disabled by policy.")
            return self._advance_after_diff_approval(task.id)

        approval = self.task_store.create_approval(task.id, "diff", approval_artifacts, diff_payload)
        task.status = "awaiting_diff_approval"
        self.task_store.update_task(task)
        self._add_event(task, "diff_approval_requested", {"approval_id": approval.id})
        self._write_index(self.task_store.get_task(task.id), "Pending approval gate: `diff`.")
        return self.task_store.get_task(task.id)

    def _advance_after_diff_approval(self, task_id: str) -> Task:
        task = self.task_store.get_task(task_id)
        if not self._latest_evaluation_passed(task.id):
            task.status = "changes_requested"
            self.task_store.update_task(task)
            self._add_event(task, "diff_approval_blocked", {"reason": "latest_evaluation_not_passed"})
            self._write_index(self.task_store.get_task(task.id), "Latest evaluation did not pass.")
            return self.task_store.get_task(task.id)
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
            base_branch=str((self.projects.get(task.project_id or "") or {}).get("default_branch", "main")),
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

    def _write_executor_policy(self, task: Task):
        artifact = self.artifact_store.write_markdown(
            task,
            "executor_policy",
            "Executor policy",
            self._executor_policy_markdown(task),
        )
        self.task_store.add_artifact(artifact)
        return artifact

    def _executor_policy_markdown(self, task: Task) -> str:
        blocked = self.projects.blocked_paths(task.project_id)
        allowed = self.projects.allowed_paths(task.project_id)
        return f"""# Executor policy

## Scope

- Worktree: `{task.worktree_path or "not created"}`
- Project: `{task.project_id or "unknown"}`
- Do not commit changes.
- Do not deploy.
- Do not edit secrets or local environment files.

## Allowed paths

{self._bullet_list(allowed or ["Any source, test, or documentation path not blocked below."])}

## Blocked paths

{self._bullet_list(blocked)}

## Limits

- Max changed files: `{self.projects.max_changed_files(task.project_id)}`
- Max diff bytes: `{self.projects.max_diff_bytes(task.project_id)}`
"""

    def _write_executor_result_artifacts(self, task: Task, result, run_id: str) -> None:
        if result.prompt:
            self.task_store.add_artifact(
                self.artifact_store.write_markdown(
                    task,
                    "executor_prompt",
                    "Executor prompt",
                    self._runtime_artifact_markdown(task, run_id, "prompt.txt", result.prompt),
                )
            )
        if result.command:
            command_text = " ".join(result.command)
            self.task_store.add_artifact(
                self.artifact_store.write_markdown(
                    task,
                    "executor_command",
                    "Executor command",
                    f"# Executor command\n\n```text\n{command_text}\n```\n",
                )
            )
        if result.stdout or self.settings.default_executor == "codex":
            self.task_store.add_artifact(
                self.artifact_store.write_markdown(
                    task,
                    "executor_stdout",
                    "Executor stdout",
                    self._runtime_artifact_markdown(task, run_id, "stdout.txt", result.stdout),
                )
            )
        if result.stderr or self.settings.default_executor == "codex":
            self.task_store.add_artifact(
                self.artifact_store.write_markdown(
                    task,
                    "executor_stderr",
                    "Executor stderr",
                    self._runtime_artifact_markdown(task, run_id, "stderr.txt", result.stderr),
                )
            )

    def _runtime_artifact_markdown(self, task: Task, run_id: str, filename: str, content: str) -> str:
        runtime_dir = self.settings.artifacts_root.parent / "runtime" / task.id / run_id
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_path = runtime_dir / filename
        runtime_path.write_text(content or "", encoding="utf-8")
        preview = (content or "").strip()
        if len(preview) > 4000:
            preview = preview[:4000] + "\n\n[Preview truncated; open the runtime file for full content.]"
        if not preview:
            preview = "(empty)"
        return f"""# Runtime artifact

Full content: `runtime://{task.id}/{run_id}/{filename}`

Filesystem path: `{runtime_path}`

## Preview

```text
{preview}
```
"""

    def _run_validation(self, task: Task):
        if not self.settings.run_tests_after_execution:
            from engineering_orchestrator.services.validation_service import ValidationResult

            return ValidationResult(status="skipped", summary="Validation is disabled by orchestrator settings.")
        commands = self.projects.test_commands(task.project_id)
        profile = self.projects.validation_profile(task.project_id)
        return self.validation_service.run(commands, task.worktree_path, validation_profile=profile)

    def _write_validation_command_outputs(self, task: Task, validation_result) -> None:
        existing_versions = [
            artifact.version or 0
            for artifact in self.task_store.list_artifacts(task.id)
            if artifact.kind == "validation_command_output"
        ]
        version_offset = max(existing_versions, default=0)
        for index, command in enumerate(validation_result.commands, start=1):
            artifact = self.artifact_store.write_markdown(
                task,
                "validation_command_output",
                f"Validation command {index}",
                self.validation_service.command_output_markdown(command),
                version=version_offset + index,
            )
            self.task_store.add_artifact(artifact)

    def _evaluate_policy(
        self,
        task: Task,
        changed_files: list[str],
        diff_text: str,
        evaluation_findings: list[dict[str, Any]] | None = None,
    ) -> tuple[str, str]:
        violations: list[str] = []
        blocked = self.projects.blocked_paths(task.project_id)
        allowed = self.projects.allowed_paths(task.project_id)
        max_changed_files = self.projects.max_changed_files(task.project_id)
        max_diff_bytes = self.projects.max_diff_bytes(task.project_id)

        if len(changed_files) > max_changed_files:
            violations.append(f"Changed file count `{len(changed_files)}` exceeds limit `{max_changed_files}`.")

        diff_bytes = len(diff_text.encode("utf-8"))
        if diff_bytes > max_diff_bytes:
            violations.append(f"Diff size `{diff_bytes}` bytes exceeds limit `{max_diff_bytes}` bytes.")

        for file_name in changed_files:
            normalized = file_name.replace("\\", "/")
            if any(self._path_matches(normalized, pattern) for pattern in blocked):
                violations.append(f"Blocked path changed: `{file_name}`.")
            if allowed and not any(self._path_matches(normalized, pattern) for pattern in allowed):
                violations.append(f"Path is outside allowed_paths: `{file_name}`.")

        structured_findings = evaluation_findings or []
        status = "failed" if violations or any(finding.get("severity") == "error" for finding in structured_findings) else "passed"
        markdown = f"""# Policy report

Status: `{status}`

## Changed files

{self._bullet_list(changed_files)}

## Limits

- Max changed files: `{max_changed_files}`
- Actual changed files: `{len(changed_files)}`
- Max diff bytes: `{max_diff_bytes}`
- Actual diff bytes: `{diff_bytes}`

## Blocked paths

{self._bullet_list(blocked)}

## Allowed paths

{self._bullet_list(allowed or ["No allow-list configured."])}

## Violations

{self._bullet_list(violations)}

## Evaluation findings

```json
{json.dumps(structured_findings, ensure_ascii=False, indent=2)}
```
"""
        return status, markdown

    def _evaluation_markdown(self, evaluation) -> str:
        return f"""# Evaluation

Status: `{evaluation.status}`
Passed: `{evaluation.passed}`
Score: `{evaluation.score if evaluation.score is not None else "none"}`

## Findings

```json
{json.dumps(evaluation.findings, ensure_ascii=False, indent=2)}
```
"""

    def _write_run_artifacts(self, task: Task, run_id: str) -> None:
        run = self.task_store.get_run(run_id)
        steps = self.task_store.list_steps(run_id)
        evaluations = self.task_store.list_evaluations(task.id)
        payload = {
            "run": run.model_dump(mode="json"),
            "steps": [step.model_dump(mode="json") for step in steps],
            "evaluations": [evaluation.model_dump(mode="json") for evaluation in evaluations if evaluation.run_id == run_id],
        }
        markdown = [
            "# Run",
            "",
            f"- ID: `{run.id}`",
            f"- Type: `{run.run_type}`",
            f"- Status: `{run.status}`",
            f"- Executor: `{run.executor or 'none'}`",
            f"- Iterations: `{run.iteration_count}`",
            f"- Stop reason: `{run.stop_reason or 'none'}`",
            "",
            "## Steps",
            "",
        ]
        if steps:
            for step in steps:
                markdown.append(f"- `{step.step_index}` `{step.step_type}`: `{step.status}` - {step.output_summary or ''}".rstrip())
        else:
            markdown.append("- None.")
        run_md = self.artifact_store.write_markdown(task, "run_report", "Run report", "\n".join(markdown) + "\n")
        run_json = self.artifact_store.write_json(task, "run_report_json", "Run report JSON", payload)
        self.task_store.add_artifact(run_md)
        self.task_store.add_artifact(run_json)

    def _path_matches(self, path: str, pattern: str) -> bool:
        normalized_pattern = pattern.replace("\\", "/")
        return path == normalized_pattern or fnmatch(path, normalized_pattern)

    def _answer_markdown(self, task: Task) -> str:
        return f"""# Answer

This request was routed as `question_only`, so Tasker closed it without creating an execution plan or requesting code-change approvals.

## Question

> {task.user_message}

## Route

- Project: `{task.project_id or "unknown"}`
- Workflow: `{task.workflow_id or "unknown"}`
- Risk: `{task.risk_level or "unknown"}`

## Answer

No source files were modified. Use this task as a durable record of the question, route decision, context artifact, and final response. A future non-mock answer provider can replace this deterministic MVP response while keeping the same artifact contract.

## Sources / Context used

- Route decision
- Project profile
- Workflow policy
- Context summary artifact
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

    def _review_markdown_structured(self, result, validation_result, evaluation, diff_stat: str) -> str:
        recommendation = "approve" if evaluation.passed else "request changes"
        validation_lines = [
            f"- `{command.command}`: `{command.status}`"
            for command in getattr(validation_result, "commands", [])
        ]
        if not validation_lines:
            validation_lines = [f"- `{validation_result.status}`: {validation_result.summary}"]
        blocked_findings = [finding for finding in evaluation.findings if finding.get("code") == "blocked_path_changed"]
        config_findings = [finding for finding in evaluation.findings if finding.get("code") == "config_change_requires_approval"]
        diff_size = "too large" if any(finding.get("code") == "diff_line_limit_exceeded" for finding in evaluation.findings) else "ok"
        return f"""# Review

## Summary

{result.summary}

## Changed files

{self._bullet_list(result.changed_files)}

## Validation

{chr(10).join(validation_lines)}

## Evaluation

- validation: `{validation_result.status}`
- blocked paths: `{"found" if blocked_findings else "none"}`
- config changes: `{"require approval" if config_findings else "none"}`
- diff size: `{diff_size}`

## Findings

```json
{json.dumps(evaluation.findings, ensure_ascii=False, indent=2)}
```

## Diff stat

```text
{diff_stat}
```

## Risks

{self._bullet_list([finding.get("message", str(finding)) for finding in evaluation.findings] or ["No evaluation findings."])}

## Recommendation

{recommendation}
"""

    def _commit_and_close(self, task_id: str) -> Task:
        task = self.task_store.get_task(task_id)
        guard_error = self._commit_guard_error(task)
        if guard_error:
            task.status = "changes_requested"
            self.task_store.update_task(task)
            self._add_event(task, "commit_blocked", {"reason": guard_error})
            blocked = self.artifact_store.write_markdown(
                task,
                "commit_result",
                "Commit result",
                f"# Commit result\n\nCommit blocked: {guard_error}\n",
            )
            self.task_store.add_artifact(blocked)
            self._write_index(self.task_store.get_task(task.id), "Commit blocked; diff must be reviewed again.")
            return self.task_store.get_task(task.id)
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

    def _latest_evaluation_passed(self, task_id: str) -> bool:
        evaluations = self.task_store.list_evaluations(task_id)
        return bool(evaluations and evaluations[-1].passed)

    def _approved_diff_approval(self, task_id: str):
        approvals = [approval for approval in self.task_store.list_approvals(task_id) if approval.gate == "diff" and approval.status == "approved"]
        return approvals[-1] if approvals else None

    def _commit_guard_error(self, task: Task) -> str | None:
        if self.settings.require_diff_approval and self._approved_diff_approval(task.id) is None:
            return "missing approved diff approval"
        if not self._latest_evaluation_passed(task.id):
            return "latest evaluation did not pass"
        unresolved = [
            approval.gate
            for approval in self.task_store.list_approvals(task.id)
            if approval.status == "pending" and approval.gate != "commit"
        ]
        if unresolved:
            return f"unresolved approvals: {', '.join(unresolved)}"
        if not task.worktree_path:
            return None
        worktree = Path(task.worktree_path)
        try:
            self.git_service.diff_check(worktree)
            current_files = self.git_service.changed_files(worktree)
        except Exception as exc:
            return f"git pre-commit observe failed: {exc}"
        approval = self._approved_diff_approval(task.id)
        payload = approval.requested_payload if approval else {}
        if "reviewed_files" in payload and sorted(list(payload.get("reviewed_files") or [])) != sorted(current_files):
            return "changed files differ from approved diff"
        return None

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
            slug_short=slugify_short(task.user_message),
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

    def _pending_gate(self, task: Task) -> str | None:
        pending = [approval for approval in self.task_store.list_approvals(task.id) if approval.status == "pending"]
        return pending[0].gate if pending else None

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
    resolved_settings = settings or load_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    orchestrator = Orchestrator(resolved_settings)
    app.state.orchestrator = orchestrator
    register_ui_routes(app, orchestrator)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/tasks", response_model=CreateTaskResponse)
    def create_task(request: CreateTaskRequest):
        return orchestrator.create_task(request)

    @app.get("/tasks")
    def list_tasks(
        status: str | None = None,
        project_id: str | None = None,
        workflow_id: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        return orchestrator.list_tasks_page(status, project_id, workflow_id, q, limit, offset)

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str):
        try:
            return orchestrator.get_task_payload(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/artifacts")
    def list_artifacts(task_id: str):
        try:
            orchestrator.get_task(task_id)
            return orchestrator.list_artifacts(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/artifacts/by-id/{artifact_id}")
    def read_artifact_by_id(task_id: str, artifact_id: str):
        try:
            return orchestrator.read_artifact_by_id(task_id, artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/artifacts/{kind}")
    def read_artifact(task_id: str, kind: str, version: int | None = None):
        try:
            return {"content": orchestrator.read_artifact(task_id, kind, version)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/cancel")
    def cancel_task(task_id: str, request: CancelTaskRequest):
        try:
            return orchestrator.cancel_task(task_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/approvals")
    def list_approvals(task_id: str):
        try:
            return {"items": orchestrator.list_approvals(task_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/events")
    def list_events(task_id: str):
        try:
            return {"items": orchestrator.list_events(task_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/context")
    def get_context(task_id: str):
        try:
            return orchestrator.get_context(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/rebuild-context")
    def rebuild_context(task_id: str):
        try:
            return orchestrator.rebuild_context(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/runs")
    def list_runs(task_id: str):
        try:
            return orchestrator.list_runs(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/jobs")
    def list_jobs(task_id: str):
        try:
            return {"items": orchestrator.list_jobs(task_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return orchestrator.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}")
    def get_run(run_id: str):
        try:
            return orchestrator.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/steps")
    def list_steps(run_id: str):
        try:
            return orchestrator.list_steps(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/approvals/{gate}", status_code=status.HTTP_202_ACCEPTED)
    def decide_approval(task_id: str, gate: str, request: ApprovalDecisionRequest):
        try:
            return orchestrator.enqueue_approval_decision(task_id, gate, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/messages", status_code=status.HTTP_202_ACCEPTED)
    def continue_task(task_id: str, request: ContinueTaskRequest):
        try:
            return orchestrator.enqueue_continue_task(task_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = create_app()
