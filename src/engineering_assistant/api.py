from __future__ import annotations

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engineering_assistant.settings import load_settings
from engineering_assistant.task_router import TaskRouter
from engineering_orchestrator.api import AdaptiveRouteRequest, Orchestrator
from engineering_orchestrator.models import (
    ApprovalDecisionRequest,
    CancelTaskRequest,
    ContinueTaskRequest,
    CreateCorrectionRequest,
    CreateCorrectionResponse,
    CreateTaskRequest,
)
from engineering_orchestrator.settings import Settings
from engineering_orchestrator.ui import register_ui_routes


class RouteRequest(BaseModel):
    message: str


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="engineering_assistant", version="0.1.0")
    resolved_settings = settings or load_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    router = TaskRouter(
        resolved_settings.projects_path,
        resolved_settings.workflows_path,
        provider=resolved_settings.router_provider,
    )
    orchestrator = Orchestrator(resolved_settings, task_router=router)
    app.state.task_router = router
    app.state.orchestrator = orchestrator
    register_ui_routes(app, orchestrator)

    @app.get("/health")
    def health():
        return {"ok": True, "app": "engineering_assistant"}

    @app.get("/health/tools")
    def tool_health():
        return orchestrator.tool_health()

    @app.post("/route")
    def route_task(request: RouteRequest):
        return router.route(request.message)

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
    def create_routing_rule(payload: dict):
        return orchestrator.create_routing_rule(payload)

    @app.get("/routing/rules/{rule_id}")
    def get_routing_rule(rule_id: str):
        try:
            return orchestrator.get_routing_rule(rule_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/routing/rules/{rule_id}")
    def update_routing_rule(rule_id: str, payload: dict):
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
    def routing_feedback(payload: dict):
        return orchestrator.add_routing_feedback(payload)

    @app.post("/tasks")
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
            job = orchestrator.job_runner.enqueue(task_id, "compact-context", lambda: orchestrator.compact_context(task_id), input={})
            return {"accepted": True, "job_id": job.id, "task_id": task_id, "status": job.status, "action": job.action}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/actions/rebuild-context", status_code=status.HTTP_202_ACCEPTED)
    def rebuild_context_action(task_id: str):
        try:
            orchestrator.get_task(task_id)
            job = orchestrator.job_runner.enqueue(task_id, "rebuild-context", lambda: orchestrator.rebuild_context(task_id), input={})
            return {"accepted": True, "job_id": job.id, "task_id": task_id, "status": job.status, "action": job.action}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/actions/retry-execution", status_code=status.HTTP_202_ACCEPTED)
    def retry_execution_action(task_id: str):
        try:
            orchestrator.get_task(task_id)
            job = orchestrator.job_runner.enqueue(task_id, "retry-execution", lambda: orchestrator._run_execution(task_id), input={})
            return {"accepted": True, "job_id": job.id, "task_id": task_id, "status": job.status, "action": job.action}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{task_id}/actions/retry-validation", status_code=status.HTTP_202_ACCEPTED)
    def retry_validation_action(task_id: str):
        try:
            orchestrator.get_task(task_id)
            job = orchestrator.job_runner.enqueue(task_id, "retry-validation", lambda: orchestrator._run_execution(task_id), input={})
            return {"accepted": True, "job_id": job.id, "task_id": task_id, "status": job.status, "action": job.action}
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
