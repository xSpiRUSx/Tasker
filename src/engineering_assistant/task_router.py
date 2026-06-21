from __future__ import annotations

from pathlib import Path

from task_router.config_loader import load_router_config
from task_router.graph import build_graph
from task_router.models import RouteDecision, RouterConfig


class TaskRouter:
    """In-process routing boundary used by the orchestrator."""

    def __init__(self, projects_path: str | Path, workflows_path: str | Path, provider: str = "mock"):
        self.projects_path = Path(projects_path)
        self.workflows_path = Path(workflows_path)
        self.provider = provider
        self.config: RouterConfig = load_router_config(self.projects_path, self.workflows_path)
        self._graph = build_graph(self.config, provider=provider)

    def route(self, message: str) -> RouteDecision:
        state = self._graph.invoke({"input_text": message})
        return state["result"]
