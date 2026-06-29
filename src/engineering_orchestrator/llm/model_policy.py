from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


ENV_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)\}$")


class ModelPolicy:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, Any] = yaml.safe_load(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    @property
    def active_profile(self) -> str:
        return str(os.getenv("TASKER_MODEL_PROFILE") or self.data.get("active_profile") or "balanced")

    def target(self, target_id: str) -> dict[str, Any]:
        targets = self.data.get("model_targets") or {}
        return dict(targets.get(target_id) or targets.get("mock") or {"runtime": "mock", "model": "mock"})

    def resolve_model(self, value: str | None) -> str:
        if not value:
            return "none"
        match = ENV_PATTERN.match(value)
        if not match:
            return value
        env_name = match.group(1)
        return os.getenv(env_name, value)

    def operation_target(self, operation: str) -> str | None:
        route = (self.data.get("operation_routes") or {}).get(operation) or {}
        return route.get("first")

    def workflow_target(self, workflow_id: str | None, phase: str, correction_mode: str | None = None) -> str | None:
        if not workflow_id:
            return None
        route = (self.data.get("workflow_routes") or {}).get(workflow_id) or {}
        value = route.get(phase)
        if isinstance(value, dict) and correction_mode:
            key = correction_mode.replace("_correction", "")
            return value.get(key) or value.get("risky")
        if isinstance(value, str):
            return None if value == "none" else value
        return None

    def profile_default(self, profile: str, requires_code_execution: bool) -> str:
        data = (self.data.get("profiles") or {}).get(profile) or {}
        key = "default_executor_target" if requires_code_execution else "default_reasoning_target"
        return str(data.get(key) or "mock")

    def allows_extra_high(self, profile: str) -> bool:
        data = (self.data.get("profiles") or {}).get(profile) or {}
        return not bool(data.get("require_user_approval_for_extra_high", False))
