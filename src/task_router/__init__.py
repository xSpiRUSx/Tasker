"""Configurable LangGraph task router."""

from task_router.config_loader import load_router_config
from task_router.graph import build_graph

__all__ = ["build_graph", "load_router_config"]
