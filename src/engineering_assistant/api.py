from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from engineering_assistant.settings import load_settings
from engineering_assistant.task_router import TaskRouter
from engineering_orchestrator.api import Orchestrator
from engineering_orchestrator.models import ApprovalDecisionRequest, ContinueTaskRequest, CreateTaskRequest
from engineering_orchestrator.settings import Settings
from engineering_orchestrator.ui import register_ui_routes


class RouteRequest(BaseModel):
    message: str


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="engineering_assistant", version="0.1.0")
    resolved_settings = settings or load_settings()
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

    @app.post("/route")
    def route_task(request: RouteRequest):
        return router.route(request.message)

    @app.post("/tasks")
    def create_task(request: CreateTaskRequest):
        return orchestrator.create_task(request)

    @app.get("/tasks")
    def list_tasks(status: str | None = None, project_id: str | None = None, limit: int = 100):
        return orchestrator.list_tasks(status, project_id, limit)

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

    @app.get("/tasks/{task_id}/approvals")
    def list_approvals(task_id: str):
        try:
            return orchestrator.list_approvals(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}/events")
    def list_events(task_id: str):
        try:
            return orchestrator.list_events(task_id)
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
