from __future__ import annotations

from engineering_orchestrator.api import Orchestrator
from engineering_orchestrator.models import CreateTaskRequest, CreateTaskResponse


def create_initial_plan(orchestrator: Orchestrator, request: CreateTaskRequest) -> CreateTaskResponse:
    return orchestrator.create_task(request)
