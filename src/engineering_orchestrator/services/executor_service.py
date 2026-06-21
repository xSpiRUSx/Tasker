from __future__ import annotations

from pathlib import Path

from engineering_orchestrator.executors.codex_executor import CodexExecutor
from engineering_orchestrator.executors.base import Executor
from engineering_orchestrator.executors.mock_executor import MockExecutor
from engineering_orchestrator.settings import Settings


class ExecutorService:
    def __init__(self, settings: Settings | None = None, artifacts_root: str | Path | None = None):
        self.settings = settings
        self.artifacts_root = Path(artifacts_root) if artifacts_root else None

    def get(self, name: str) -> Executor:
        if name == "codex":
            if self.settings is None or self.artifacts_root is None:
                raise ValueError("Codex executor requires settings and artifacts_root.")
            return CodexExecutor(
                self.artifacts_root,
                codex_bin=self.settings.codex_bin,
                model=self.settings.codex_model,
                timeout_seconds=self.settings.codex_timeout_seconds,
            )
        return MockExecutor()
