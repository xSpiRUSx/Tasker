from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def _project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "config").exists():
            return parent
    return current.parents[2]


def _resolve_path(base_dir: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


@dataclass(frozen=True)
class Settings:
    task_id_prefix: str
    timezone: str
    sqlite_path: Path
    artifacts_root: Path
    task_folder_template: str
    router_provider: str
    projects_path: Path
    workflows_path: Path
    planner_provider: str
    planner_model: str | None
    planner_timeout_seconds: int
    default_executor: str
    codex_bin: str
    codex_model: str | None
    codex_timeout_seconds: int
    worktrees_root: Path
    branch_template: str
    run_tests_after_execution: bool
    require_plan_approval: bool
    require_diff_approval: bool
    require_commit_approval: bool
    loop_default_max_iterations: int = 2
    loop_default_max_runtime_seconds: int = 1800
    loop_default_max_changed_files: int = 12
    loop_default_max_diff_lines: int = 1200
    loop_repair_on_validation_failure: bool = True
    loop_require_human_on_blocked_path: bool = True
    loop_require_human_on_config_change: bool = True
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
    )
    model_policy_path: Path | None = None
    token_budgets_path: Path | None = None
    runtime_root: Path | None = None


def load_settings(config_path: str | Path | None = None) -> Settings:
    root = _project_root()
    load_dotenv(root / ".env", override=False)
    path = Path(config_path) if config_path else root / "config" / "orchestrator.yml"
    path = path.resolve()
    base_dir = path.parent.parent if path.parent.name == "config" else path.parent

    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    orchestrator = data.get("orchestrator", {})
    storage = data.get("storage", {})
    artifacts = data.get("artifacts", {})
    router = data.get("router", {})
    planning = data.get("planning", {})
    execution = data.get("execution", {})
    validation = data.get("validation", {})
    approvals = data.get("approvals", {})
    loop = data.get("loop", {})
    web = data.get("web", {})

    sqlite_path = os.getenv("ORCHESTRATOR_SQLITE_PATH", storage.get("sqlite_path", "./data/orchestrator.sqlite3"))
    artifacts_root = os.getenv("ORCHESTRATOR_ARTIFACTS_ROOT", artifacts.get("root_path", "./data/obsidian-tasks"))
    worktrees_root = os.getenv("ORCHESTRATOR_WORKTREES_ROOT", execution.get("worktrees_root", "./data/worktrees"))
    router_provider = os.getenv("ORCHESTRATOR_ROUTER_PROVIDER", router.get("provider", "mock"))
    planner_provider = os.getenv("ORCHESTRATOR_PLANNER_PROVIDER", planning.get("provider", "mock"))
    planner_model = os.getenv("ORCHESTRATOR_PLANNER_MODEL", planning.get("model"))
    default_executor = os.getenv("ORCHESTRATOR_DEFAULT_EXECUTOR", execution.get("default_executor", "mock"))
    codex_model = os.getenv("ORCHESTRATOR_CODEX_MODEL", execution.get("codex_model"))
    cors_origins_raw = os.getenv("TASKER_CORS_ORIGINS")
    cors_origins = (
        [origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()]
        if cors_origins_raw
        else list(
            web.get("cors_origins")
            or [
                "http://127.0.0.1:5173",
                "http://localhost:5173",
                "http://127.0.0.1:5174",
                "http://localhost:5174",
                "http://127.0.0.1:5175",
                "http://localhost:5175",
            ]
        )
    )

    return Settings(
        task_id_prefix=str(orchestrator.get("task_id_prefix", "ENG")),
        timezone=str(orchestrator.get("timezone", "UTC")),
        sqlite_path=_resolve_path(base_dir, sqlite_path),
        artifacts_root=_resolve_path(base_dir, artifacts_root),
        task_folder_template=str(artifacts.get("task_folder_template", "{task_id} - {project_id} - {slug_short}")),
        router_provider=str(router_provider),
        projects_path=_resolve_path(base_dir, router.get("projects_path", "./config/projects.yml")),
        workflows_path=_resolve_path(base_dir, router.get("workflows_path", "./config/workflows.yml")),
        model_policy_path=_resolve_path(base_dir, data.get("model_policy_path", "./config/model_policy.yml")),
        token_budgets_path=_resolve_path(base_dir, data.get("token_budgets_path", "./config/token_budgets.yml")),
        runtime_root=_resolve_path(base_dir, data.get("runtime_root", "./data/runtime")),
        planner_provider=str(planner_provider),
        planner_model=str(planner_model) if planner_model else None,
        planner_timeout_seconds=int(os.getenv("ORCHESTRATOR_PLANNER_TIMEOUT_SECONDS", planning.get("timeout_seconds", 900))),
        default_executor=str(default_executor),
        codex_bin=str(os.getenv("ORCHESTRATOR_CODEX_BIN", execution.get("codex_bin", "codex"))),
        codex_model=str(codex_model) if codex_model else None,
        codex_timeout_seconds=int(os.getenv("ORCHESTRATOR_CODEX_TIMEOUT_SECONDS", execution.get("codex_timeout_seconds", 1800))),
        worktrees_root=_resolve_path(base_dir, worktrees_root),
        branch_template=str(execution.get("branch_template", "ai/{task_id}-{slug}")),
        run_tests_after_execution=bool(validation.get("run_tests_after_execution", True)),
        require_plan_approval=bool(approvals.get("require_plan_approval", True)),
        require_diff_approval=bool(approvals.get("require_diff_approval", True)),
        require_commit_approval=bool(approvals.get("require_commit_approval", True)),
        loop_default_max_iterations=int(loop.get("default_max_iterations", 2)),
        loop_default_max_runtime_seconds=int(loop.get("default_max_runtime_seconds", 1800)),
        loop_default_max_changed_files=int(loop.get("default_max_changed_files", 12)),
        loop_default_max_diff_lines=int(loop.get("default_max_diff_lines", 1200)),
        loop_repair_on_validation_failure=bool(loop.get("repair_on_validation_failure", True)),
        loop_require_human_on_blocked_path=bool(loop.get("require_human_on_blocked_path", True)),
        loop_require_human_on_config_change=bool(loop.get("require_human_on_config_change", True)),
        cors_origins=tuple(str(origin) for origin in cors_origins),
    )
