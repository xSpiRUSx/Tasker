from __future__ import annotations

from pathlib import Path

from engineering_orchestrator.settings import Settings, load_settings as load_orchestrator_settings


def project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "config").exists():
            return parent
    return current.parents[2]


def load_settings(config_path: str | Path | None = None) -> Settings:
    path = Path(config_path) if config_path else project_root() / "config" / "orchestrator.yml"
    return load_orchestrator_settings(path)
