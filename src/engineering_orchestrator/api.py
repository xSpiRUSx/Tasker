from __future__ import annotations

import json
import hashlib
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Protocol

import yaml
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from engineering_orchestrator.corrections import LinkedTaskDetectionResult, LinkedTaskDetector
from engineering_orchestrator.harness import ContextBuilder, PromptBuilder
from engineering_orchestrator.llm import ModelPolicy, ModelSelectionRequest, ModelSelector, PromptBudgeter
from engineering_orchestrator.llm.prompt_budgeter import PromptBudgetError
from engineering_orchestrator.loop import Evaluator, LoopPolicy, Observer, RepairPlanner
from engineering_orchestrator.models import (
    ApprovalDecisionRequest,
    CancelTaskRequest,
    ContinueTaskRequest,
    CorrectionRequest,
    CreateTaskRequest,
    CreateCorrectionRequest,
    CreateCorrectionResponse,
    CreateTaskResponse,
    JobAcceptedResponse,
    RouteDecision,
    Task,
)
from engineering_orchestrator.services.approval_service import ApprovalService
from engineering_orchestrator.services.artifact_store import ArtifactStore, slugify, slugify_short
from engineering_orchestrator.services.correction_classifier import CorrectionClassifier, CorrectionClassifierInput
from engineering_orchestrator.services.event_service import EventService
from engineering_orchestrator.services.executor_service import ExecutorService
from engineering_orchestrator.services.git_service import GitService
from engineering_orchestrator.services.job_runner import JobRunner
from engineering_orchestrator.services.planning_service import PlanningService
from engineering_orchestrator.services.project_registry import ProjectRegistry
from engineering_orchestrator.services.review_service import ReviewService
from engineering_orchestrator.services.task_store import TaskStore, utc_now
from engineering_orchestrator.services.tool_health import ToolHealthService
from engineering_orchestrator.services.validation_service import ValidationService
from engineering_orchestrator.services.workflow_registry import WorkflowRegistry
from engineering_orchestrator.settings import Settings, load_settings
from engineering_orchestrator.ui import register_ui_routes
from task_router.adaptive import AdaptiveRoutingDecision, AdaptiveRoutingService, RoutingContext
from task_router.adaptive.config import load_adaptive_routing_config


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


class AdaptiveRouteRequest(BaseModel):
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    debug: bool = False


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
        model_policy_path = self._config_path(settings.model_policy_path, "model_policy.yml")
        token_budgets_path = self._config_path(settings.token_budgets_path, "token_budgets.yml")
        self.token_budgets = self._load_yaml(token_budgets_path)
        self.model_policy = ModelPolicy(model_policy_path)
        self.model_selector = ModelSelector(self.model_policy, self.projects, self.token_budgets)
        self.prompt_budgeter = PromptBudgeter(token_budgets_path)
        adaptive_config_path = self._config_path(None, "adaptive_routing.yml")
        self.adaptive_routing_config = load_adaptive_routing_config(adaptive_config_path)
        self.adaptive_router = AdaptiveRoutingService(
            self.adaptive_routing_config,
            task_resolver=self._resolve_adaptive_task_refs,
        )
        self.tool_health_service = ToolHealthService(
            self.projects,
            settings.codex_bin,
            settings.worktrees_root,
            settings.runtime_root or settings.artifacts_root.parent / "runtime",
        )
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
        self.correction_classifier = CorrectionClassifier()
        self.linked_task_detector = LinkedTaskDetector()
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
        task = self.task_store.get_task(task.id)
        if task.status == "awaiting_parent_task_clarification":
            self._write_index(task, "Choose the parent task before planning.")
            return self._create_response(task, None)

        if route.workflow_id in {None, "clarify"}:
            task.status = "awaiting_clarification"
            self.task_store.update_task(task)
            self._add_event(task, "awaiting_clarification", {"warnings": route.warnings})
            self._write_index(task, "Clarification is required before planning.")
            return self._create_response(task, None)

        self._collect_context(task)
        task = self._write_tool_health(task.id)
        if route.workflow_id == "question_only":
            task = self._answer_question_and_close(task.id)
            return self._create_response(task, None)
        if route.workflow_id == "task_correction":
            task = self._start_linked_correction(task.id)
            return self._create_response(task, self._pending_gate(task))

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

    def list_corrections(self, task_id: str):
        self.task_store.get_task(task_id)
        return self.task_store.list_correction_requests(task_id)

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

    def list_model_decisions(self, task_id: str):
        self.task_store.get_task(task_id)
        return self.task_store.list_model_decisions(task_id)

    def list_prompt_builds(self, task_id: str):
        self.task_store.get_task(task_id)
        return self.task_store.list_prompt_builds(task_id)

    def route_adaptive(self, message: str, context: RoutingContext | dict[str, Any] | None = None) -> AdaptiveRoutingDecision:
        routing_context = context if isinstance(context, RoutingContext) else RoutingContext(**(context or {}))
        return self._run_adaptive_routing(message, routing_context)

    def list_routing_rules(self, status: str | None = None) -> list[dict[str, Any]]:
        return self.task_store.list_routing_rules(status)

    def create_routing_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.task_store.create_routing_rule(payload)

    def get_routing_rule(self, rule_id: str) -> dict[str, Any]:
        return self.task_store.get_routing_rule(rule_id)

    def update_routing_rule(self, rule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.task_store.update_routing_rule(rule_id, payload)

    def promote_routing_rule(self, rule_id: str) -> dict[str, Any]:
        rule = self.task_store.set_routing_rule_status(rule_id, "active")
        self._append_routing_eval_cases(rule)
        return rule

    def reject_routing_rule(self, rule_id: str) -> dict[str, Any]:
        return self.task_store.set_routing_rule_status(rule_id, "rejected")

    def disable_routing_rule(self, rule_id: str) -> dict[str, Any]:
        return self.task_store.set_routing_rule_status(rule_id, "disabled")

    def list_routing_suggestions(self, status: str | None = None) -> list[dict[str, Any]]:
        return self.task_store.list_routing_rule_suggestions(status)

    def get_routing_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        return self.task_store.get_routing_rule_suggestion(suggestion_id)

    def promote_routing_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        suggestion = self.task_store.set_routing_rule_suggestion_status(suggestion_id, "promoted")
        for item in suggestion.get("suggested_rules") or []:
            rule_id = item.get("rule_id")
            if rule_id:
                self._append_routing_eval_cases(self.task_store.get_routing_rule(str(rule_id)))
        return suggestion

    def reject_routing_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        return self.task_store.set_routing_rule_suggestion_status(suggestion_id, "rejected")

    def add_routing_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        rule_id = payload.get("rule_id")
        if rule_id and payload.get("accepted") is False:
            self.task_store.add_routing_false_positive(
                str(rule_id),
                self.adaptive_routing_config.safety.disable_after_false_positives,
            )
        return self.task_store.add_routing_feedback(
            payload.get("task_id"),
            payload.get("original_route"),
            payload.get("final_route"),
            payload.get("user_correction"),
            payload.get("accepted"),
        )

    def tool_health(self) -> dict[str, Any]:
        return self.tool_health_service.global_report()

    def task_tool_health(self, task_id: str) -> dict[str, Any]:
        task = self.task_store.get_task(task_id)
        report = self.tool_health_service.task_report(task.project_id)
        artifact = self.artifact_store.write_markdown(task, "tool_health_report", "Tool health", self.tool_health_service.markdown(report))
        self.task_store.add_artifact(artifact)
        return report

    def _write_tool_health(self, task_id: str) -> Task:
        task = self.task_store.get_task(task_id)
        report = self.tool_health_service.task_report(task.project_id)
        if report.get("manual_review_required") or report.get("mode") == "degraded_no_mcp":
            route = dict(task.route_decision or {})
            route["planning_mode"] = report.get("mode")
            route["manual_review_required"] = bool(report.get("manual_review_required"))
            if report.get("manual_review_required"):
                route["validation_warning"] = "manual_review_required"
            task.route_decision = route
            self.task_store.update_task(task)
        artifact = self.artifact_store.write_markdown(task, "tool_health_report", "Tool health", self.tool_health_service.markdown(report))
        self.task_store.add_artifact(artifact)
        self._add_event(task, "tool_health_checked", {"mode": report.get("mode"), "manual_review_required": report.get("manual_review_required")})
        return self.task_store.get_task(task.id)

    def compact_context(self, task_id: str) -> dict[str, Any]:
        task = self.task_store.get_task(task_id)
        decision = self._record_model_decision(
            task,
            None,
            ModelSelectionRequest(
                task_id=task.id,
                operation="compact_context",
                workflow_id=task.workflow_id,
                project_id=task.project_id,
                risk_level=task.risk_level,
            ),
        )
        latest_correction = self.task_store.list_correction_requests(task.id)[-1:] or []
        changed_files: list[str] = []
        if task.worktree_path:
            try:
                changed_files = self.git_service.changed_files(Path(task.worktree_path))
            except Exception:
                changed_files = []
        content = f"""# Context compact

## Current task goal

{task.user_message}

## Route

- Project: `{task.project_id or "unknown"}`
- Workflow: `{task.workflow_id or "unknown"}`
- Risk: `{task.risk_level or "unknown"}`

## Latest correction request

{latest_correction[0].user_comment if latest_correction else "None."}

## Current changed files

{self._bullet_list(changed_files)}

## Do-not-touch rules

{self._bullet_list(self.projects.blocked_paths(task.project_id))}

## Model decision

- Target: `{decision.selected_target}`
- Runtime: `{decision.runtime}`
- Model: `{decision.model}`
- Reason: {decision.reason}
"""
        artifact = self.artifact_store.write_markdown(task, "context_compact", "Context compact", content)
        payload = {
            "task_id": task.id,
            "changed_files": changed_files,
            "model_decision_id": decision.id,
            "blocked_paths": self.projects.blocked_paths(task.project_id),
        }
        json_artifact = self.artifact_store.write_json(task, "context_compact_json", "Context compact JSON", payload)
        self.task_store.add_artifact(artifact)
        self.task_store.add_artifact(json_artifact)
        self._add_event(task, "context_compacted", {"artifact_id": artifact.id, "model_decision_id": decision.id})
        self._write_index(self.task_store.get_task(task.id), "Context was compacted and can be used for retry.")
        return payload

    def repair_state(self, task_id: str) -> dict[str, Any]:
        task = self.task_store.get_task(task_id)
        before = task.model_dump(mode="json")
        findings: list[str] = []
        if task.status.startswith("awaiting_") and self.task_store.get_current_approval_gate(task.id) is None:
            findings.append("awaiting status has no pending approval")
        if task.status in {"executing", "planning", "executing_correction"}:
            active = [job for job in self.task_store.list_jobs(task.id) if job.status in {"queued", "running"}]
            if not active:
                findings.append("running status has no active job")
                task.status = "changes_requested"
        if task.status == "changes_requested" and not self.task_store.list_correction_requests(task.id):
            findings.append("changes_requested has no correction request")
        if task.status in {"closed", "cancelled"} and task.closed_at is None:
            findings.append("terminal status missing closed_at")
            task.closed_at = utc_now()
        if task.status not in {"closed", "cancelled"} and task.closed_at is not None:
            findings.append("non-terminal status had closed_at")
            task.closed_at = None
        if task.worktree_path and not Path(task.worktree_path).exists():
            findings.append("worktree path is missing")
            task.status = "changes_requested"
        self.task_store.update_task(task)
        after = self.task_store.get_task(task.id).model_dump(mode="json")
        report = {"task_id": task.id, "findings": findings, "before": before, "after": after}
        self._add_event(task, "task_state_repaired", {"findings": findings})
        artifact = self.artifact_store.write_markdown(
            self.task_store.get_task(task.id),
            "diagnosis",
            "Task state repair",
            "# Task state repair\n\n```json\n" + json.dumps(report, ensure_ascii=False, indent=2) + "\n```\n",
        )
        self.task_store.add_artifact(artifact)
        return report

    def cancel_job(self, job_id: str):
        return self.job_runner.cancel(job_id)

    def _load_yaml(self, path: Path | None) -> dict[str, Any]:
        if path and path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {}

    def _config_path(self, configured: Path | None, filename: str) -> Path:
        if configured and configured.exists():
            return configured
        sibling = Path(self.settings.projects_path).parent / filename
        if sibling.exists():
            return sibling
        repo_config = Path(__file__).resolve().parents[2] / "config" / filename
        return repo_config

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
                correction_request = CreateCorrectionRequest(
                    source_gate=gate,
                    source_approval_id=approval.id,
                    comment=request.comment or "Apply the requested diff correction.",
                    action="run_without_new_plan",
                )
                self.create_correction(task_id, correction_request, resolved_approval=approval)
                return self.task_store.get_task(task_id)
            task.status = "plan_rejected" if gate == "plan" else "changes_requested"
            self.task_store.update_task(task)
            self._add_event(task, f"{gate}_approval_rejected", {"comment": request.comment})
            self._write_index(task, f"Gate `{gate}` was rejected.")
            return self.task_store.get_task(task_id)

        self.task_store.resolve_approval(approval.id, "approved", request.comment)
        self._add_event(task, f"{gate}_approval_approved", {"comment": request.comment})
        correction_id = approval.requested_payload.get("correction_request_id")
        if correction_id and gate == "plan":
            correction = self.task_store.get_correction_request(task_id, str(correction_id))
            return self._run_correction_execution(task_id, correction)
        if gate == "plan" or gate in PRE_EXECUTION_GATE_ORDER:
            return self._advance_after_pre_execution_approval(task_id)
        if gate == "diff":
            if correction_id:
                self.task_store.update_correction_request_status(str(correction_id), "diff_approved")
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
            input=request.model_dump(mode="json"),
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
            input={"gate": gate, **request.model_dump(mode="json")},
        )
        return JobAcceptedResponse(job_id=job.id, task_id=task_id, status=job.status, action=job.action)

    def _route_task(self, task: Task) -> RouteDecision:
        task.status = "routing"
        self.task_store.update_task(task)

        route_payload: dict[str, Any] | None = None
        linked_detection: LinkedTaskDetectionResult | None = None
        adaptive_decision = self._run_adaptive_routing(
            task.user_message,
            RoutingContext(task_id=task.id, source=task.source, recent_task_ids=[]),
        )
        if self._should_use_adaptive_for_task(adaptive_decision):
            route = self._route_from_adaptive_decision(task, adaptive_decision)
            route_payload = route.model_dump() | {
                "adaptive_routing": adaptive_decision.model_dump(mode="json", exclude={"diagnostics"}),
            }
        else:
            linked_detection = self.linked_task_detector.detect(task.user_message)
        if route_payload is None and linked_detection and linked_detection.found:
            self._record_model_decision(
                task,
                None,
                ModelSelectionRequest(
                    task_id=task.id,
                    operation="detect_linked_task",
                    estimated_prompt_chars=len(task.user_message),
                ),
            )
            route = self._route_linked_correction(task, linked_detection)
            route_payload = route.model_dump()
        elif route_payload is None and self.task_router is not None:
            external_route = self.task_router.route(task.user_message)
            route_payload = self._model_dump(external_route)
            route = self._normalize_route_decision(route_payload)
        elif route_payload is None:
            route = self._mock_route_task(task)
            route_payload = route.model_dump()

        task.project_id = route.project_id
        task.project_name = route.project_name
        task.project_path = route.project_path
        task.workflow_id = route.workflow_id
        task.workflow_name = route.workflow_name
        task.risk_level = route.risk_level
        if linked_detection and linked_detection.found:
            route_payload = {
                **(route_payload or route.model_dump()),
                "linked_task_detection": linked_detection.model_dump(mode="json"),
                "parent_task_id": task.parent_task_id,
                "related_task_ids": task.related_task_ids,
                "correction_source": task.correction_source,
            }
        task.route_decision = route_payload
        if task.status != "awaiting_parent_task_clarification":
            task.status = "routed" if route.workflow_id not in {None, "clarify"} else "awaiting_clarification"
        self.task_store.update_task(task)
        task = self._rename_artifact_folder_for_route(self.task_store.get_task(task.id))
        self._record_model_decision(
            task,
            None,
            ModelSelectionRequest(
                task_id=task.id,
                operation="route_task",
                workflow_id=route.workflow_id,
                project_id=route.project_id,
                complexity=route.complexity,
                risk_level=route.risk_level,
            ),
        )

        artifact = self.artifact_store.write_markdown(task, "route_decision", "Route decision", self._route_markdown(task, route))
        self.task_store.add_artifact(artifact)
        if "adaptive_routing" in (route_payload or {}):
            self._write_routing_diagnostics(task, adaptive_decision)
        self._add_event(task, "task_routed", route.model_dump())
        self._write_index(self.task_store.get_task(task.id))
        return route

    def _run_adaptive_routing(self, message: str, context: RoutingContext) -> AdaptiveRoutingDecision:
        active_rules = self.task_store.list_routing_rules("active")
        recent_tasks = [
            {
                "id": task.id,
                "title": task.user_message[:160],
                "status": task.status,
                "project_id": task.project_id,
            }
            for task in self.task_store.list_tasks(limit=self.adaptive_routing_config.cheap_classifier.recent_tasks_limit)
        ]

        def save_suggestions(result) -> list[str]:
            if not self.adaptive_routing_config.learning.enabled:
                return []
            suggestions = [
                item.model_dump(mode="json")
                for item in result.learned_rule_suggestions
                if item.confidence >= self.adaptive_routing_config.learning.min_confidence_for_suggestion
            ]
            if not suggestions:
                return []
            record = self.task_store.create_routing_rule_suggestion(
                context.task_id,
                message,
                result.model_dump(mode="json"),
                suggestions,
            )
            return [str(item.get("rule_id")) for item in record.get("suggested_rules") or [] if item.get("rule_id")]

        decision = self.adaptive_router.route(
            message,
            context,
            active_rules=active_rules,
            projects=self.projects.projects,
            recent_tasks=recent_tasks,
            save_suggestions=save_suggestions,
        )
        diagnostics = decision.diagnostics
        self.task_store.add_routing_diagnostic(
            context.task_id,
            message,
            diagnostics.get("deterministic_result"),
            diagnostics.get("classifier_result"),
            diagnostics.get("final_result") or decision.model_dump(mode="json", exclude={"diagnostics"}),
            decision.used_classifier,
        )
        if decision.used_classifier:
            request = ModelSelectionRequest(
                task_id=context.task_id,
                operation=self.adaptive_routing_config.cheap_classifier.operation,
                project_id=decision.project_id,
                workflow_id=decision.workflow_id,
                estimated_prompt_chars=int(diagnostics.get("classifier_prompt_chars") or 0),
            )
            if context.task_id:
                self._record_model_decision(self.task_store.get_task(context.task_id), None, request)
            else:
                selected = self.model_selector.select(request)
                self.task_store.add_model_decision(
                    None,
                    None,
                    request.operation,
                    selected.profile,
                    selected.target_id,
                    selected.runtime,
                    selected.model,
                    selected.reasoning_effort,
                    selected.reason,
                    request.estimated_prompt_chars,
                    selected.max_prompt_chars,
                )
        for rule_id in decision.matched_rules:
            if rule_id.startswith("rule-"):
                self.task_store.increment_routing_rule_hit(rule_id)
        return decision

    def _should_use_adaptive_for_task(self, decision: AdaptiveRoutingDecision) -> bool:
        if decision.requires_clarification and decision.parent_task_candidates:
            return True
        if decision.route_type in {"linked_correction", "question", "task_action"} and (
            decision.parent_task_id or decision.parent_task_candidates
        ):
            return True
        return False

    def _route_from_adaptive_decision(self, task: Task, decision: AdaptiveRoutingDecision) -> RouteDecision:
        if decision.requires_clarification:
            warning = decision.reason
            if decision.clarification_question and decision.clarification_question not in warning:
                warning = f"{decision.clarification_question} {warning}".strip()
            route = RouteDecision(
                normalized_task=task.user_message.strip(),
                intent="clarify",
                task_kind=decision.task_kind or "unknown",
                complexity="trivial",
                project_id=decision.project_id,
                project_name=None,
                project_path=None,
                workflow_id="clarify",
                workflow_name="Clarify routing",
                risk_level="medium",
                risk_flags=["adaptive_routing_uncertain"],
                approval_gates=["clarification"],
                warnings=[warning],
                rationale=decision.reason,
                requires_spec=False,
            )
            if decision.parent_task_candidates:
                task.status = "awaiting_parent_task_clarification"
            return route

        parent = self._get_parent_from_adaptive(decision)
        if decision.route_type == "linked_correction" and parent is not None:
            workflow = self.workflows.get("task_correction") or {}
            task.parent_task_id = parent.id
            task.related_task_ids = sorted(set([*task.related_task_ids, parent.id]))
            task.correction_source = "adaptive_routing" if decision.used_classifier or decision.source == "learned_rule" else "linked_task_message"
            return RouteDecision(
                normalized_task=task.user_message.strip(),
                intent="code_change",
                task_kind=decision.task_kind or "linked_correction",
                complexity="trivial",
                project_id=parent.project_id,
                project_name=parent.project_name,
                project_path=parent.project_path,
                workflow_id="task_correction",
                workflow_name=str(workflow.get("name") or "Task correction"),
                risk_level="low" if parent.risk_level != "high" else "medium",
                risk_flags=["linked_task_correction", "adaptive_routing"],
                approval_gates=list(workflow.get("approval_gates") or ["diff", "commit"]),
                warnings=[],
                rationale=decision.reason,
                requires_spec=False,
            )

        if decision.route_type in {"question", "task_action"}:
            workflow = self.workflows.get("question_only") or {}
            if parent is not None:
                task.parent_task_id = parent.id
                task.related_task_ids = sorted(set([*task.related_task_ids, parent.id]))
                task.project_id = parent.project_id
            return RouteDecision(
                normalized_task=task.user_message.strip(),
                intent="question",
                task_kind=decision.route_type,
                complexity="simple",
                project_id=(parent.project_id if parent else decision.project_id),
                project_name=(parent.project_name if parent else None),
                project_path=(parent.project_path if parent else None),
                workflow_id="question_only",
                workflow_name=str(workflow.get("name") or "Question only"),
                risk_level="low",
                risk_flags=["adaptive_routing"],
                approval_gates=[],
                warnings=[],
                rationale=decision.reason,
                requires_spec=False,
            )

        return self._mock_route_task(task)

    def _get_parent_from_adaptive(self, decision: AdaptiveRoutingDecision) -> Task | None:
        if not decision.parent_task_id:
            return None
        try:
            return self.task_store.get_task(decision.parent_task_id)
        except KeyError:
            return None

    def _resolve_adaptive_task_refs(self, refs: list[str], context: RoutingContext) -> tuple[str | None, list[str], str | None]:
        candidates: list[str] = []
        for ref in refs:
            if "-" in ref:
                try:
                    task = self.task_store.get_task(ref.upper())
                    candidates.append(task.id)
                except KeyError:
                    continue
            elif ref.isdigit():
                matches = [
                    candidate.id
                    for candidate in self.task_store.list_tasks(limit=500)
                    if candidate.id != context.task_id and candidate.id.endswith(f"-{ref}")
                ]
                candidates.extend(matches)
        candidates = sorted(set(candidates))
        if len(candidates) == 1:
            return candidates[0], candidates, None
        if len(candidates) > 1:
            return None, candidates, f"Task reference is ambiguous: {', '.join(candidates)}."
        if refs:
            return None, refs, f"Referenced task was not found: {', '.join(refs)}."
        return None, [], None

    def _write_routing_diagnostics(self, task: Task, decision: AdaptiveRoutingDecision) -> None:
        diagnostics = decision.diagnostics
        markdown = self._routing_diagnostics_markdown(decision)
        artifact = self.artifact_store.write_markdown(task, "routing_diagnostics", "Routing diagnostics", markdown)
        json_artifact = self.artifact_store.write_json(task, "routing_diagnostics_json", "Routing diagnostics JSON", diagnostics)
        self.task_store.add_artifact(artifact)
        self.task_store.add_artifact(json_artifact)

    def _routing_diagnostics_markdown(self, decision: AdaptiveRoutingDecision) -> str:
        diagnostics = decision.diagnostics
        deterministic = diagnostics.get("deterministic_result") or {}
        classifier = diagnostics.get("classifier_result") or {}
        suggested = decision.suggested_rule_ids or []
        return f"""# Routing diagnostics

## Final decision

- Route type: {decision.route_type}
- Workflow: {decision.workflow_id or "unknown"}
- Project: {decision.project_id or "unknown"}
- Parent task: {decision.parent_task_id or "none"}
- Source: {decision.source}
- Confidence: {decision.confidence:.2f}

## Deterministic pass

- Confidence: {float(deterministic.get("confidence") or 0):.2f}
- Matched rules: {", ".join(deterministic.get("matched_rules") or []) or "none"}
- Reason: {"; ".join(deterministic.get("reasons") or []) or "none"}

## Cheap classifier

- Used: {"yes" if decision.used_classifier else "no"}
- Model target: cheap_classifier
- Reason: {classifier.get("reason") or "not used"}

## Suggested rules

{self._bullet_list([f"{rule_id}: pending" for rule_id in suggested])}
"""

    def _append_routing_eval_cases(self, rule: dict[str, Any]) -> None:
        if not self.adaptive_routing_config.learning.create_eval_cases:
            return
        eval_dir = Path(self.settings.projects_path).resolve().parent.parent / "evals" / "routing"
        eval_dir.mkdir(parents=True, exist_ok=True)
        path = eval_dir / "adaptive_rules.yml"
        lines: list[str] = []
        for index, example in enumerate(rule.get("positive_examples") or [], 1):
            lines.extend(
                [
                    f"- id: {rule['id']}-positive-{index}",
                    f"  input: {json.dumps(example, ensure_ascii=False)}",
                    "  expected:",
                    f"    route_type: {rule.get('target_route_type') or 'unknown'}",
                    "",
                ]
            )
        for index, example in enumerate(rule.get("negative_examples") or [], 1):
            lines.extend(
                [
                    f"- id: {rule['id']}-negative-{index}",
                    f"  input: {json.dumps(example, ensure_ascii=False)}",
                    "  expected:",
                    f"    not_route_type: {rule.get('target_route_type') or 'unknown'}",
                    "",
                ]
            )
        if lines:
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(lines))

    def _route_linked_correction(self, task: Task, detection: LinkedTaskDetectionResult) -> RouteDecision:
        parent, warning = self._resolve_parent_task(task, detection)
        if parent is None:
            route = RouteDecision(
                normalized_task=task.user_message.strip(),
                intent="code_change",
                task_kind="linked_correction",
                complexity="trivial",
                project_id=None,
                project_name=None,
                project_path=None,
                workflow_id="clarify",
                workflow_name="Clarify missing task info",
                risk_level="medium",
                risk_flags=["linked_task_unresolved"],
                approval_gates=["clarification"],
                warnings=[warning or "Parent task could not be resolved."],
                rationale=f"{detection.reason} Parent task resolution needs clarification.",
                requires_spec=False,
            )
            task.status = "awaiting_parent_task_clarification"
            task.route_decision = route.model_dump() | {
                "linked_task_detection": detection.model_dump(mode="json"),
                "clarification_type": "parent_task",
            }
            self.task_store.update_task(task)
            return route

        workflow = self.workflows.get("task_correction") or {}
        route = RouteDecision(
            normalized_task=task.user_message.strip(),
            intent="code_change",
            task_kind="linked_correction",
            complexity="trivial",
            project_id=parent.project_id,
            project_name=parent.project_name,
            project_path=parent.project_path,
            workflow_id="task_correction",
            workflow_name=str(workflow.get("name") or "Task correction"),
            risk_level="low" if parent.risk_level != "high" else "medium",
            risk_flags=["linked_task_correction"],
            approval_gates=list(workflow.get("approval_gates") or ["diff", "commit"]),
            warnings=[],
            rationale=f"{detection.reason} Resolved parent task `{parent.id}`; routed as lightweight correction.",
            requires_spec=False,
        )
        task.parent_task_id = parent.id
        task.related_task_ids = sorted(set([*task.related_task_ids, parent.id]))
        task.correction_source = "linked_task_message"
        return route

    def _resolve_parent_task(self, task: Task, detection: LinkedTaskDetectionResult) -> tuple[Task | None, str | None]:
        if detection.parent_task_id:
            try:
                parent = self.task_store.get_task(detection.parent_task_id)
            except KeyError:
                return None, f"Referenced parent task `{detection.parent_task_id}` was not found."
            if parent.id == task.id:
                return None, "A task cannot use itself as the parent correction task."
            return parent, None

        reference = detection.extracted_reference
        if reference and reference.isdigit():
            matches = [
                candidate
                for candidate in self.task_store.list_tasks(limit=500)
                if candidate.id != task.id and candidate.id.endswith(f"-{reference}")
            ]
            if len(matches) == 1:
                return matches[0], None
            if len(matches) > 1:
                return None, f"Task number `{reference}` matches multiple tasks: {', '.join(item.id for item in matches)}."
            return None, f"Task number `{reference}` was not found."

        if detection.needs_latest_task_lookup:
            candidates = [
                candidate
                for candidate in self.task_store.list_tasks(limit=50)
                if candidate.id != task.id
                and (task.user_id is None or candidate.user_id == task.user_id)
                and candidate.status != "cancelled"
            ]
            if candidates:
                return candidates[0], None
            return None, "No previous task is available for this user/context."

        return None, "Parent task reference could not be resolved."

    def _mock_route_task(self, task: Task) -> RouteDecision:
        project = self.projects.find_for_message(task.user_message)
        intent, task_kind, complexity = self._classify(task.user_message)
        workflow = None
        message_lower = task.user_message.lower()
        if self._is_1c_project(project):
            if self._looks_1c_business_change(message_lower):
                task_kind = "configuration_change"
                complexity = "medium"
                workflow = self.workflows.get("1c_business_logic_change")
            elif self._looks_1c_metadata_change(message_lower):
                task_kind = "configuration_change"
                complexity = "medium"
                workflow = self.workflows.get("simple_dev_with_config")
            elif self._looks_1c_bugfix_patch(message_lower):
                task_kind = "code_patch"
                complexity = "simple"
                workflow = self.workflows.get("1c_bugfix_patch")
        if workflow is None:
            workflow = self.workflows.select(intent, task_kind, complexity)

        risk_flags = []
        for area in (project or {}).get("risky_areas", []):
            if str(area).lower() in message_lower:
                risk_flags.append(str(area))
        if task_kind in {"configuration_change", "dependency_change", "security_change"}:
            risk_flags.append(task_kind)
        risk_level = "low" if (workflow or {}).get("id") == "1c_bugfix_patch" and not risk_flags else (
            "high" if risk_flags or complexity in {"complex", "epic"} else "medium"
        )

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

    def _is_1c_project(self, project: dict[str, Any] | None) -> bool:
        return bool(project and str(project.get("project_type") or "").lower() == "1c")

    def _looks_1c_bugfix_patch(self, text: str) -> bool:
        patch_signals = [
            "ошибка запроса",
            "не работает запрос",
            "исправь ошибку",
            "stacktrace",
            "в одном модуле",
            "одна функция",
            "содержимое объекта данных",
            "temporary table",
            "query error",
            "bsl",
        ]
        return any(signal in text for signal in patch_signals)

    def _looks_1c_metadata_change(self, text: str) -> bool:
        metadata_signals = [
            "форма",
            "форму",
            "реквизит",
            "команд",
            "роль",
            "права",
            "metadata",
            "requisite",
            "form",
            "role",
            "permission",
        ]
        return any(signal in text for signal in metadata_signals)

    def _looks_1c_business_change(self, text: str) -> bool:
        business_signals = [
            "акцепт",
            "ценообраз",
            "очередь отправки",
            "обмен",
            "регистр",
            "проведение",
            "документ lifecycle",
            "business process",
            "posting",
            "exchange",
            "pricing",
        ]
        return any(signal in text for signal in business_signals)

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

    def _record_model_decision(self, task: Task, run_id: str | None, request: ModelSelectionRequest):
        decision = self.model_selector.select(request)
        record = self.task_store.add_model_decision(
            task.id,
            run_id,
            request.operation,
            decision.profile,
            decision.target_id,
            decision.runtime,
            decision.model,
            decision.reasoning_effort,
            decision.reason,
            request.estimated_prompt_chars,
            decision.max_prompt_chars,
        )
        self._write_model_decision_artifacts(task)
        return record

    def _record_static_model_decision(
        self,
        task: Task,
        run_id: str | None,
        operation: str,
        selected_target: str,
        runtime: str,
        model: str,
        reason: str,
        estimated_prompt_chars: int = 0,
        max_prompt_chars: int = 0,
    ):
        record = self.task_store.add_model_decision(
            task.id,
            run_id,
            operation,
            self.model_policy.active_profile,
            selected_target,
            runtime,
            model,
            None,
            reason,
            estimated_prompt_chars,
            max_prompt_chars,
        )
        self._write_model_decision_artifacts(task)
        return record

    def _write_model_decision_artifacts(self, task: Task) -> None:
        records = self.task_store.list_model_decisions(task.id)
        if not records:
            return
        lines = ["# Model decisions", ""]
        for record in records:
            lines.extend(
                [
                    f"## {record.operation}",
                    "",
                    f"- Selected target: `{record.selected_target}`",
                    f"- Runtime: `{record.runtime}`",
                    f"- Model: `{record.model}`",
                    f"- Reasoning effort: `{record.reasoning_effort or 'none'}`",
                    f"- Reason: {record.reason}",
                    f"- Prompt budget chars: `{record.max_prompt_chars}`",
                    "",
                ]
            )
        md = self.artifact_store.write_markdown(task, "model_decisions", "Model decisions", "\n".join(lines))
        js = self.artifact_store.write_json(
            task,
            "model_decisions_json",
            "Model decisions JSON",
            [record.model_dump(mode="json") for record in records],
        )
        self.task_store.add_artifact(md)
        self.task_store.add_artifact(js)

    def _write_prompt_manifest_artifact(self, task: Task, manifest) -> None:
        status_value = getattr(
            manifest,
            "status",
            "ok" if manifest.total_chars <= manifest.budget_chars else "prompt_too_large",
        )
        included_entries = [self._prompt_entry_summary(entry) for entry in manifest.included_artifacts]
        excluded_entries = [self._prompt_entry_exclusion(entry) for entry in manifest.excluded_artifacts]
        content = f"""# Prompt manifest

Operation: `{manifest.operation}`
Status: `{status_value}`
Total chars: `{manifest.total_chars}`
Budget chars: `{manifest.budget_chars}`

## Included artifacts

{self._bullet_list(included_entries)}

## Excluded artifacts

{self._bullet_list(excluded_entries)}
"""
        artifact = self.artifact_store.write_markdown(task, "prompt_manifest", "Prompt manifest", content)
        self.task_store.add_artifact(artifact)

    def _prompt_entry_summary(self, entry) -> str:
        data = entry if isinstance(entry, dict) else entry.model_dump(mode="json")
        version = data.get("version") or "latest"
        return f"{data.get('kind')} v{version}: {data.get('chars', 0)} chars"

    def _prompt_entry_exclusion(self, entry) -> str:
        data = entry if isinstance(entry, dict) else entry.model_dump(mode="json")
        return f"{data.get('kind')} ({data.get('reason') or 'excluded'})"

    def _create_plan(self, task: Task, revision_comment: str | None = None):
        task.status = "planning"
        self.task_store.update_task(task)
        route = RouteDecision(**(task.route_decision or {}))
        context_artifact = self.task_store.get_artifact(task.id, "context_summary")
        context_markdown = self.artifact_store.read_text(context_artifact) if context_artifact else ""
        if revision_comment:
            context_markdown = context_markdown.rstrip() + f"\n\n## Latest correction request\n\n{revision_comment}\n"
        if task.workflow_id == "1c_bugfix_patch":
            operation = "create_1c_bugfix_patch_plan"
        elif self.projects.validation_profile(task.project_id) == "1c":
            operation = "create_1c_business_spec"
        else:
            operation = "create_complex_spec" if route.requires_spec or task.risk_level == "high" else "create_simple_plan"
        self._record_model_decision(
            task,
            None,
            ModelSelectionRequest(
                task_id=task.id,
                operation=operation,
                workflow_id=task.workflow_id,
                project_id=task.project_id,
                complexity=route.complexity,
                risk_level=task.risk_level,
                estimated_prompt_chars=len(context_markdown),
            ),
        )
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

    def create_correction(
        self,
        task_id: str,
        request: CreateCorrectionRequest,
        resolved_approval=None,
    ) -> CreateCorrectionResponse:
        task = self.task_store.get_task(task_id)
        comment = request.comment.strip()
        if not comment:
            raise ValueError("Correction comment is required.")

        source_approval = resolved_approval
        if source_approval is None and request.source_approval_id:
            source_approval = next(
                (approval for approval in self.task_store.list_approvals(task_id) if approval.id == request.source_approval_id),
                None,
            )
        if source_approval is None and request.source_gate:
            approvals = [approval for approval in self.task_store.list_approvals(task_id) if approval.gate == request.source_gate]
            source_approval = approvals[-1] if approvals else None

        changed_files = []
        if source_approval is not None:
            changed_files = list(source_approval.requested_payload.get("reviewed_files") or [])
            pending = self.task_store.get_pending_approval(task_id, source_approval.gate)
            if pending is not None and pending.id == source_approval.id:
                self.task_store.resolve_approval(source_approval.id, "rejected", comment)

        task.status = "classifying_correction"
        self.task_store.update_task(task)
        self._record_model_decision(
            task,
            None,
            ModelSelectionRequest(
                task_id=task.id,
                operation="classify_correction",
                workflow_id=task.workflow_id,
                project_id=task.project_id,
                risk_level=task.risk_level,
                estimated_prompt_chars=len(comment),
            ),
        )
        classifier_result = self.correction_classifier.classify(
            CorrectionClassifierInput(
                comment=comment,
                action=request.action,
                changed_files=changed_files,
                risk_flags=list((task.route_decision or {}).get("risk_flags") or []),
                task_has_approved_plan=self._has_approved_plan(task_id),
            )
        )

        approved_for_execution = classifier_result.approved_for_execution and not classifier_result.requires_plan_approval
        status = "correction_requested"
        if approved_for_execution:
            status = "executing_correction"
        elif classifier_result.mode == "new_task":
            status = "correction_blocked"
        response_status = status
        correction = self.task_store.create_correction_request(
            task_id=task_id,
            source_gate=request.source_gate,
            source_approval_id=source_approval.id if source_approval else request.source_approval_id,
            source_artifact_id=request.source_artifact_id,
            user_comment=comment,
            mode=classifier_result.mode,
            status=status,
            approved_for_execution=approved_for_execution,
            requires_plan_approval=classifier_result.requires_plan_approval,
            requires_spec_addendum=classifier_result.requires_spec_addendum,
            classifier_result=classifier_result.model_dump(mode="json"),
        )
        self._write_correction_artifacts(task, correction, changed_files)
        self._add_event(
            task,
            "correction_request_created",
            {
                "correction_id": correction.id,
                "mode": correction.mode,
                "approved_for_execution": approved_for_execution,
                "requires_plan_approval": classifier_result.requires_plan_approval,
            },
        )

        if approved_for_execution:
            self._run_correction_execution(task_id, correction)
        elif classifier_result.mode == "new_task":
            task = self.task_store.get_task(task_id)
            task.status = "correction_blocked"
            self.task_store.update_task(task)
            self._write_index(task, "Correction is blocked because it appears to be a new linked task.")
        else:
            self._request_correction_plan_approval(task_id, correction)
            response_status = "awaiting_correction_plan_approval"

        return CreateCorrectionResponse(
            correction_id=correction.id,
            mode=correction.mode,
            status=response_status,
            approved_for_execution=correction.approved_for_execution,
            requires_plan_approval=correction.requires_plan_approval,
            requires_spec_addendum=correction.requires_spec_addendum,
        )

    def _start_linked_correction(self, task_id: str) -> Task:
        task = self.task_store.get_task(task_id)
        if not task.parent_task_id:
            task.status = "awaiting_parent_task_clarification"
            self.task_store.update_task(task)
            self._add_event(task, "linked_correction_blocked", {"reason": "missing_parent_task_id"})
            self._write_index(task, "Choose the parent task before running this correction.")
            return self.task_store.get_task(task.id)

        try:
            parent = self.task_store.get_task(task.parent_task_id)
        except KeyError:
            task.status = "awaiting_parent_task_clarification"
            self.task_store.update_task(task)
            self._add_event(task, "linked_correction_blocked", {"reason": "parent_task_not_found", "parent_task_id": task.parent_task_id})
            self._write_index(task, "Parent task was not found.")
            return self.task_store.get_task(task.id)

        changed_files = self._latest_reviewed_files(parent.id)
        classifier_result = self.correction_classifier.classify(
            CorrectionClassifierInput(
                comment=task.user_message,
                action="run_without_new_plan",
                changed_files=changed_files,
                risk_flags=list((parent.route_decision or {}).get("risk_flags") or []),
                task_has_approved_plan=True,
            )
        )
        approved_for_execution = (
            classifier_result.mode in {"micro_correction", "minor_correction"}
            and not classifier_result.requires_plan_approval
            and not classifier_result.requires_spec_addendum
        )
        correction = self.task_store.create_correction_request(
            task_id=task.id,
            source_gate="linked_task_message",
            source_approval_id=None,
            source_artifact_id=None,
            user_comment=task.user_message,
            mode=classifier_result.mode,
            status="executing_correction" if approved_for_execution else "correction_requested",
            approved_for_execution=approved_for_execution,
            requires_plan_approval=classifier_result.requires_plan_approval,
            requires_spec_addendum=classifier_result.requires_spec_addendum,
            classifier_result=classifier_result.model_dump(mode="json"),
        )
        self._write_correction_artifacts(task, correction, changed_files)
        self._record_model_decision(
            task,
            None,
            ModelSelectionRequest(
                task_id=task.id,
                operation="classify_correction",
                workflow_id=task.workflow_id,
                project_id=task.project_id,
                risk_level=task.risk_level,
                estimated_prompt_chars=len(task.user_message),
            ),
        )
        self._record_static_model_decision(
            task,
            None,
            "planning",
            "skipped",
            "none",
            "none",
            "Micro/minor linked correction does not require full planning.",
        )
        self._add_event(
            task,
            "linked_correction_created",
            {
                "parent_task_id": parent.id,
                "correction_id": correction.id,
                "mode": correction.mode,
                "approved_for_execution": approved_for_execution,
            },
        )
        if approved_for_execution:
            return self._run_correction_execution(task.id, correction)
        if classifier_result.mode == "new_task":
            task.status = "correction_blocked"
            self.task_store.update_task(task)
            self._write_index(task, "Linked correction is blocked because it appears to be a separate task.")
            return self.task_store.get_task(task.id)
        return self._request_correction_plan_approval(task.id, correction)

    def _latest_reviewed_files(self, task_id: str) -> list[str]:
        approvals = [approval for approval in self.task_store.list_approvals(task_id) if approval.gate == "diff"]
        if not approvals:
            return []
        return list(approvals[-1].requested_payload.get("reviewed_files") or [])

    def _has_approved_plan(self, task_id: str) -> bool:
        return any(approval.gate == "plan" and approval.status == "approved" for approval in self.task_store.list_approvals(task_id))

    def _write_correction_artifacts(self, task: Task, correction: CorrectionRequest, changed_files: list[str]) -> None:
        version = int(correction.id.rsplit("-", 1)[-1])
        request_artifact = self.artifact_store.write_markdown(
            task,
            "correction_request",
            f"Correction {version:03d}",
            self._correction_request_markdown(correction),
            version=version,
            frontmatter={
                "correction_id": correction.id,
                "source_gate": correction.source_gate,
                "source_approval_id": correction.source_approval_id,
                "mode": correction.mode,
                "approved_for_execution": str(correction.approved_for_execution).lower(),
            },
        )
        self.task_store.add_artifact(request_artifact)

        context_artifact = self.artifact_store.write_markdown(
            task,
            "correction_context",
            f"Correction {version:03d} context",
            self._correction_context_markdown(task, correction, changed_files),
            version=version,
        )
        self.task_store.add_artifact(context_artifact)

        if correction.requires_spec_addendum:
            addendum = self.artifact_store.write_markdown(
                task,
                "spec_addendum",
                f"Spec addendum for {correction.id}",
                self._spec_addendum_markdown(task, correction),
                version=version,
            )
            self.task_store.add_artifact(addendum)

    def _request_correction_plan_approval(self, task_id: str, correction: CorrectionRequest) -> Task:
        task = self.task_store.get_task(task_id)
        artifacts = [
            artifact
            for artifact in self.task_store.list_artifacts(task.id)
            if artifact.kind in {"correction_request", "correction_context", "spec_addendum"}
            and artifact.version == int(correction.id.rsplit("-", 1)[-1])
        ]
        approval = self.task_store.create_approval(
            task.id,
            "plan",
            [artifact.id for artifact in artifacts],
            {
                "approves": ["focused correction execution"],
                "correction_request_id": correction.id,
                "correction_mode": correction.mode,
                "spec_addendum": correction.requires_spec_addendum,
            },
        )
        self.task_store.update_correction_request_status(correction.id, "awaiting_correction_plan_approval")
        task.status = "awaiting_plan_approval"
        self.task_store.update_task(task)
        self._add_event(task, "correction_plan_approval_requested", {"approval_id": approval.id, "correction_id": correction.id})
        self._write_index(self.task_store.get_task(task.id), "Correction plan is pending approval gate: `plan`.")
        return self.task_store.get_task(task_id)

    def _correction_execution_artifacts(self, task: Task, correction: CorrectionRequest) -> list:
        version = int(correction.id.rsplit("-", 1)[-1])
        allowed = {"correction_request", "correction_context", "spec_addendum", "executor_policy"}
        return [
            artifact
            for artifact in self.task_store.list_artifacts(task.id)
            if artifact.kind in allowed and (artifact.version in {None, version} or artifact.kind == "executor_policy")
        ]

    def _correction_request_markdown(self, correction: CorrectionRequest) -> str:
        return f"""# Correction {correction.id.rsplit("-", 1)[-1]}

## User comment

{correction.user_comment}

## Execution policy

- Do not create new features.
- Do not regenerate the full plan.
- Do not modify unrelated files.
- Preserve already useful changes.
- Only fix the reviewed diff according to the comment.

## Approval

This correction was approved by the user review comment.

## Classifier

- Mode: `{correction.mode}`
- Approved for execution: `{str(correction.approved_for_execution).lower()}`
- Requires plan approval: `{str(correction.requires_plan_approval).lower()}`
- Requires spec addendum: `{str(correction.requires_spec_addendum).lower()}`
- Reason: {correction.classifier_result.get("reason", "No reason recorded.")}
"""

    def _correction_context_markdown(self, task: Task, correction: CorrectionRequest, changed_files: list[str]) -> str:
        allowed_paths = self.projects.allowed_paths(task.project_id)
        blocked_paths = self.projects.blocked_paths(task.project_id)
        parent = None
        if task.parent_task_id:
            try:
                parent = self.task_store.get_task(task.parent_task_id)
            except KeyError:
                parent = None
        diff_summary = ""
        diff_task_id = parent.id if parent else task.id
        diff_artifact = self.task_store.get_artifact(diff_task_id, "diff_summary")
        if diff_artifact is not None:
            diff_summary = self.artifact_store.read_text(diff_artifact)
            if len(diff_summary) > 5000:
                diff_summary = diff_summary[:5000] + "\n\n[Diff summary truncated for correction context.]"
        return f"""# Correction context

You are applying a user-requested correction to an already reviewed diff.

The user has already approved execution of this correction by submitting this review comment.

Do not regenerate the full plan.
Do not expand task scope.
Only modify the current diff according to the comment.
Do not touch unrelated files.

## User correction

{correction.user_comment}

## Current changed files

{self._bullet_list(changed_files)}

## Allowed files

{self._bullet_list(allowed_paths or ["Any source, test, or documentation path not blocked below."])}

## Blocked files

{self._bullet_list(blocked_paths)}

## Approved task summary

- Task: `{parent.id if parent else task.id}`
- Original request: {(parent.user_message if parent else task.user_message)}
- Project: `{task.project_id or "unknown"}`
- Workflow: `{parent.workflow_id if parent else task.workflow_id or "unknown"}`
- Correction task: `{task.id}`

## Current diff summary

{diff_summary or "No diff summary artifact is available."}
"""

    def _spec_addendum_markdown(self, task: Task, correction: CorrectionRequest) -> str:
        return f"""# Spec Addendum

## Task

`{task.id}`

## Correction

`{correction.id}` / `{correction.mode}`

## User comment

{correction.user_comment}

## Approval reason

{correction.classifier_result.get("reason", "Correction changes requirements or risky areas.")}
"""

    def _correction_result_markdown(self, correction: CorrectionRequest, changed_files: list[str], diff_stat: str) -> str:
        return f"""# Correction result

## Correction

`{correction.id}` / `{correction.mode}`

## Status

Awaiting updated diff approval.

## Changed files

{self._bullet_list(changed_files)}

## Diff stat

```text
{diff_stat}
```
"""

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

    def _run_correction_execution(self, task_id: str, correction: CorrectionRequest) -> Task:
        return self._run_execution(task_id, correction)

    def _run_execution(self, task_id: str, correction: CorrectionRequest | None = None) -> Task:
        task = self.task_store.get_task(task_id)
        is_correction = correction is not None
        if is_correction and correction.mode == "micro_correction":
            operation = "execute_micro_correction"
        elif task.workflow_id == "1c_bugfix_patch":
            operation = "execute_1c_bugfix_patch"
        else:
            operation = "execute_complex_code_change" if task.risk_level == "high" else "execute_simple_code_change"
        decision = self.model_selector.select(
            ModelSelectionRequest(
                task_id=task.id,
                operation=operation,
                workflow_id=task.workflow_id,
                project_id=task.project_id,
                risk_level=task.risk_level,
                correction_mode=correction.mode if correction else None,
                requires_code_execution=True,
            )
        )
        run = self.task_store.create_run(
            task.id,
            "correction" if is_correction else "execution",
            executor=self.settings.default_executor,
            model=decision.model if self.settings.default_executor == "codex" else None,
            correction_request_id=correction.id if correction else None,
        )
        model_decision_record = self.task_store.add_model_decision(
            task.id,
            run.id,
            operation,
            decision.profile,
            decision.target_id,
            decision.runtime,
            decision.model,
            decision.reasoning_effort,
            decision.reason,
            0,
            decision.max_prompt_chars,
        )
        self._write_model_decision_artifacts(task)
        if is_correction:
            task.status = "executing_correction"
            self.task_store.update_task(task)
            self.task_store.update_correction_request_status(correction.id, "executing_correction")
            self._add_event(task, "correction_execution_started", {"run_id": run.id, "correction_id": correction.id})
        else:
            task.status = "approved_for_execution"
            self.task_store.update_task(task)
            self._add_event(task, "approved_for_execution", {"run_id": run.id})

        if self.settings.default_executor == "codex" and not task.worktree_path:
            task = self._prepare_worktree(task)
        if self.settings.default_executor == "codex":
            self._write_executor_policy(task)

        task.status = "executing_correction" if is_correction else "executing"
        self.task_store.update_task(task)
        execution_artifacts = (
            self._correction_execution_artifacts(task, correction) if is_correction else self.task_store.list_artifacts(task.id)
        )
        prompt_operation = "execute_micro_correction" if is_correction else "execute_code"
        prompt_bundle = self.prompt_budgeter.build_bundle(
            task,
            prompt_operation,
            execution_artifacts,
            self.artifact_store.root_path,
            run_id=run.id,
            model_decision_id=model_decision_record.id,
        )
        prompt_build = self.task_store.add_prompt_build(
            task.id,
            run.id,
            prompt_bundle.operation,
            prompt_bundle.total_chars,
            prompt_bundle.budget_chars,
            prompt_bundle.included_artifacts,
            prompt_bundle.excluded_artifacts,
            "ok" if prompt_bundle.total_chars <= prompt_bundle.budget_chars else "prompt_too_large",
        )
        prompt_bundle.prompt_build_id = prompt_build.id
        self._write_prompt_manifest_artifact(task, prompt_bundle)
        try:
            self.prompt_budgeter.ensure_bundle_within_budget(prompt_bundle)
        except PromptBudgetError as exc:
            task.status = "prompt_too_large"
            self.task_store.update_task(task)
            self.task_store.finish_run(run.id, "failed", iteration_count=0, stop_reason="prompt_too_large")
            self._add_event(task, "prompt_too_large", {"error": str(exc), "run_id": run.id})
            self._write_index(self.task_store.get_task(task.id), "Prompt is too large. Compact context and retry.")
            return self.task_store.get_task(task.id)
        result = self.executor.execute(
            task,
            execution_artifacts,
            prompt_bundle=prompt_bundle,
            model_decision=decision,
        )
        self._write_executor_result_artifacts(task, result, run.id)
        self._add_event(task, "execution_completed", result.model_dump())

        if result.status != "success":
            execution = self.artifact_store.write_markdown(
                task,
                "execution_log",
                "Execution log",
                self._execution_markdown(task, result),
            )
            self.task_store.add_artifact(execution)
            self.task_store.add_step(
                run.id,
                1,
                "execute",
                "failed",
                input_summary=f"Executor `{self.settings.default_executor}`",
                output_summary=result.summary,
                artifact_ids=[execution.id],
                error=result.logs,
            )
            task.status = (
                "prompt_too_large"
                if "prompt_too_large" in result.summary
                else "correction_blocked"
                if is_correction
                else "changes_requested"
            )
            self.task_store.update_task(task)
            if is_correction:
                self.task_store.update_correction_request_status(correction.id, "correction_blocked")
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
            self._write_index(
                self.task_store.get_task(task.id),
                "Correction execution failed." if is_correction else "Execution failed. Awaiting corrections.",
            )
            return self.task_store.get_task(task.id)

        task.status = "validating_correction" if is_correction else "validating"
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
        execution = self.artifact_store.write_markdown(
            task,
            "execution_log",
            "Execution log",
            self._execution_markdown(task, result),
        )
        self.task_store.add_artifact(execution)
        self.task_store.add_step(
            run.id,
            1,
            "execute",
            "passed",
            input_summary=f"Executor `{self.settings.default_executor}`",
            output_summary=result.summary,
            artifact_ids=[execution.id],
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
                task.status = "correction_blocked" if is_correction else "changes_requested"
                stop_reason = loop_evaluation.status
            self.task_store.update_task(task)
            if is_correction:
                self.task_store.update_correction_request_status(correction.id, "correction_blocked")
            self.task_store.finish_run(run.id, loop_evaluation.status, iteration_count=1, stop_reason=stop_reason)
            self._write_run_artifacts(task, run.id)
            self._write_index(
                self.task_store.get_task(task.id),
                "Correction evaluation did not pass." if is_correction else "Evaluation did not pass. Awaiting corrections.",
            )
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
        diff_payload = {
            "approves": ["commit gate", "close task"],
            "reviewed_files": reviewed_files,
            "approved_diff_hash": self._text_hash(diff_text),
            "approved_changed_files_hash": self._json_hash(sorted(reviewed_files)),
            "approved_diff_stat_hash": self._text_hash(diff_stat),
            "approved_diff_artifact_id": diff_patch.id if diff_patch is not None else None,
        }
        if not self.settings.require_diff_approval:
            self._add_event(task, "diff_approval_skipped", {"artifact_ids": approval_artifacts})
            self._write_index(self.task_store.get_task(task.id), "Diff approval is disabled by policy.")
            return self._advance_after_diff_approval(task.id)

        if is_correction:
            result_artifact = self.artifact_store.write_markdown(
                task,
                "correction_result",
                f"{correction.id} result",
                self._correction_result_markdown(correction, result.changed_files, diff_stat),
                version=int(correction.id.rsplit("-", 1)[-1]),
            )
            self.task_store.add_artifact(result_artifact)
            approval_artifacts.append(result_artifact.id)
            diff_payload["correction_request_id"] = correction.id
            self.task_store.update_correction_request_status(correction.id, "awaiting_correction_diff_approval")

        approval = self.task_store.create_approval(task.id, "diff", approval_artifacts, diff_payload)
        task.status = "awaiting_correction_diff_approval" if is_correction else "awaiting_diff_approval"
        self.task_store.update_task(task)
        self._add_event(
            task,
            "correction_diff_approval_requested" if is_correction else "diff_approval_requested",
            {"approval_id": approval.id, "correction_id": correction.id if correction else None},
        )
        self._write_index(
            self.task_store.get_task(task.id),
            "Review updated diff for the correction." if is_correction else "Pending approval gate: `diff`.",
        )
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
        self._record_static_model_decision(
            task,
            None,
            "commit_message",
            "deterministic",
            "deterministic",
            "none",
            "Commit message uses the deterministic Tasker template.",
        )
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
            self._write_runtime_file(task, run_id, "executor-prompt.txt", result.prompt)
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
            self._write_runtime_file(task, run_id, "executor-stdout.log", result.stdout)
        if result.stderr or self.settings.default_executor == "codex":
            self._write_runtime_file(task, run_id, "executor-stderr.log", result.stderr)

    def _runtime_dir(self, task: Task, run_id: str) -> Path:
        runtime_root = self.settings.runtime_root or self.settings.artifacts_root.parent / "runtime"
        return Path(runtime_root) / task.id / run_id

    def _write_runtime_file(self, task: Task, run_id: str, filename: str, content: str) -> Path:
        runtime_dir = self._runtime_dir(task, run_id)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_path = runtime_dir / filename
        runtime_path.write_text(content or "", encoding="utf-8")
        return runtime_path

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
        runtime_dir = self._runtime_dir(task, run_id)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_run_path = runtime_dir / "run.json"
        runtime_run_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        markdown = [
            "# Run",
            "",
            f"- ID: `{run.id}`",
            f"- Type: `{run.run_type}`",
            f"- Status: `{run.status}`",
            f"- Executor: `{run.executor or 'none'}`",
            f"- Iterations: `{run.iteration_count}`",
            f"- Stop reason: `{run.stop_reason or 'none'}`",
            f"- Runtime run JSON: `runtime://{task.id}/{run.id}/run.json`",
            f"- Runtime directory: `{runtime_dir}`",
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
        self.task_store.add_artifact(run_md)

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
        if (
            getattr(validation_result, "profile", "") == "1c"
            and validation_result.status == "skipped"
            and getattr(validation_result, "manual_review_required", False)
        ):
            recommendation = "manual_review_required" if evaluation.passed else "request changes"
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
- manual review required: `{'yes' if getattr(validation_result, "manual_review_required", False) else 'no'}`
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
        self._record_static_model_decision(
            task,
            None,
            "git_commit",
            "deterministic",
            "git",
            "none",
            "Commit operation is a deterministic GitService call.",
        )
        guard_error = self._commit_guard_error(task)
        if guard_error:
            task.status = "awaiting_diff_reapproval" if "diff" in guard_error else "changes_requested"
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
        route = task.route_decision or {}
        task_kind = str(route.get("task_kind") or "task")
        commit_type = "fix" if task_kind in {"bugfix", "code_patch", "linked_correction"} else "chore"
        scope = slugify(task.project_id or "tasker", fallback="tasker").replace("-", "_")
        summary = slugify(task.user_message, fallback="task").replace("-", " ")[:72].strip()
        changed_files = self._latest_reviewed_files(task.id)
        bullets = changed_files[:5] or ["Prepared reviewed task changes."]
        evaluations = self.task_store.list_evaluations(task.id)
        validation_status = evaluations[-1].status if evaluations else "not recorded"
        body = "\n".join(f"- {item}" for item in bullets)
        return (
            f"{commit_type}({scope}): {summary}\n\n"
            f"Task: {task.id}\n\n"
            f"{body}\n\n"
            "Validation:\n"
            f"- {validation_status}"
        )

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
            current_diff = self.git_service.diff_patch(worktree)
            current_diff_stat = self.git_service.diff_stat(worktree)
        except Exception as exc:
            return f"git pre-commit observe failed: {exc}"
        approval = self._approved_diff_approval(task.id)
        payload = approval.requested_payload if approval else {}
        if "reviewed_files" in payload and sorted(list(payload.get("reviewed_files") or [])) != sorted(current_files):
            return "changed files differ from approved diff"
        if payload.get("approved_changed_files_hash") and payload["approved_changed_files_hash"] != self._json_hash(sorted(current_files)):
            return "changed files differ from approved diff"
        if payload.get("approved_diff_hash") and payload["approved_diff_hash"] != self._text_hash(current_diff):
            return "diff content differs from approved diff"
        if payload.get("approved_diff_stat_hash") and payload["approved_diff_stat_hash"] != self._text_hash(current_diff_stat):
            return "diff stat differs from approved diff"
        return None

    def _text_hash(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _json_hash(self, value: Any) -> str:
        return self._text_hash(json.dumps(value, ensure_ascii=False, sort_keys=True))

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
- Parent task: `{task.parent_task_id or "none"}`
- Correction source: `{task.correction_source or "none"}`
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

    @app.get("/health/tools")
    def tool_health():
        return orchestrator.tool_health()

    @app.post("/route/adaptive")
    def route_adaptive(request: AdaptiveRouteRequest):
        context = {**request.context, "debug": request.debug or bool(request.context.get("debug"))}
        decision = orchestrator.route_adaptive(request.message, context)
        payload = decision.model_dump(mode="json")
        if not context.get("debug"):
            payload.pop("diagnostics", None)
        return payload

    @app.get("/routing/rules")
    def list_routing_rules(status: str | None = None):
        return {"items": orchestrator.list_routing_rules(status)}

    @app.post("/routing/rules")
    def create_routing_rule(payload: dict[str, Any]):
        return orchestrator.create_routing_rule(payload)

    @app.get("/routing/rules/{rule_id}")
    def get_routing_rule(rule_id: str):
        try:
            return orchestrator.get_routing_rule(rule_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/routing/rules/{rule_id}")
    def update_routing_rule(rule_id: str, payload: dict[str, Any]):
        try:
            return orchestrator.update_routing_rule(rule_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/routing/rules/{rule_id}/promote")
    def promote_routing_rule(rule_id: str):
        try:
            return orchestrator.promote_routing_rule(rule_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/routing/rules/{rule_id}/reject")
    def reject_routing_rule(rule_id: str):
        try:
            return orchestrator.reject_routing_rule(rule_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/routing/rules/{rule_id}/disable")
    def disable_routing_rule(rule_id: str):
        try:
            return orchestrator.disable_routing_rule(rule_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/routing/suggestions")
    def list_routing_suggestions(status: str | None = None):
        return {"items": orchestrator.list_routing_suggestions(status)}

    @app.get("/routing/suggestions/{suggestion_id}")
    def get_routing_suggestion(suggestion_id: str):
        try:
            return orchestrator.get_routing_suggestion(suggestion_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/routing/suggestions/{suggestion_id}/promote")
    def promote_routing_suggestion(suggestion_id: str):
        try:
            return orchestrator.promote_routing_suggestion(suggestion_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/routing/suggestions/{suggestion_id}/reject")
    def reject_routing_suggestion(suggestion_id: str):
        try:
            return orchestrator.reject_routing_suggestion(suggestion_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/routing/feedback")
    def routing_feedback(payload: dict[str, Any]):
        return orchestrator.add_routing_feedback(payload)

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

    @app.get("/tasks/{task_id}/corrections")
    def list_corrections(task_id: str):
        try:
            return {"items": orchestrator.list_corrections(task_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/corrections/{correction_id}")
    def get_correction(task_id: str, correction_id: str):
        try:
            orchestrator.get_task(task_id)
            return orchestrator.task_store.get_correction_request(task_id, correction_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/corrections", response_model=CreateCorrectionResponse)
    def create_correction(task_id: str, request: CreateCorrectionRequest):
        try:
            return orchestrator.create_correction(task_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @app.get("/tasks/{task_id}/tool-health")
    def task_tool_health(task_id: str):
        try:
            return orchestrator.task_tool_health(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/model-decisions")
    def list_model_decisions(task_id: str):
        try:
            return {"items": orchestrator.list_model_decisions(task_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/prompt-builds")
    def list_prompt_builds(task_id: str):
        try:
            return {"items": orchestrator.list_prompt_builds(task_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/rebuild-context")
    def rebuild_context(task_id: str):
        try:
            return orchestrator.rebuild_context(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/actions/compact-context", status_code=status.HTTP_202_ACCEPTED)
    def compact_context_action(task_id: str):
        try:
            orchestrator.get_task(task_id)
            job = orchestrator.job_runner.enqueue(
                task_id,
                "compact-context",
                lambda: orchestrator.compact_context(task_id),
                input={},
            )
            return JobAcceptedResponse(job_id=job.id, task_id=task_id, status=job.status, action=job.action)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/actions/rebuild-context", status_code=status.HTTP_202_ACCEPTED)
    def rebuild_context_action(task_id: str):
        try:
            orchestrator.get_task(task_id)
            job = orchestrator.job_runner.enqueue(
                task_id,
                "rebuild-context",
                lambda: orchestrator.rebuild_context(task_id),
                input={},
            )
            return JobAcceptedResponse(job_id=job.id, task_id=task_id, status=job.status, action=job.action)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/actions/retry-execution", status_code=status.HTTP_202_ACCEPTED)
    def retry_execution_action(task_id: str):
        try:
            orchestrator.get_task(task_id)
            job = orchestrator.job_runner.enqueue(
                task_id,
                "retry-execution",
                lambda: orchestrator._run_execution(task_id),
                input={},
            )
            return JobAcceptedResponse(job_id=job.id, task_id=task_id, status=job.status, action=job.action)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/actions/retry-validation", status_code=status.HTTP_202_ACCEPTED)
    def retry_validation_action(task_id: str):
        try:
            orchestrator.get_task(task_id)
            job = orchestrator.job_runner.enqueue(
                task_id,
                "retry-validation",
                lambda: orchestrator._run_execution(task_id),
                input={},
            )
            return JobAcceptedResponse(job_id=job.id, task_id=task_id, status=job.status, action=job.action)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/actions/skip-validation-manual")
    def skip_validation_manual_action(task_id: str):
        try:
            task = orchestrator.get_task(task_id)
            task.status = "awaiting_diff_approval"
            orchestrator.task_store.update_task(task)
            orchestrator._add_event(task, "validation_skipped_manual", {})
            return orchestrator.get_task_payload(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/repair-state")
    def repair_state(task_id: str):
        try:
            return orchestrator.repair_state(task_id)
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

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        try:
            return orchestrator.cancel_job(job_id)
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
