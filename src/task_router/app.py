from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from task_router.config_loader import load_router_config
from task_router.graph import build_graph


def default_config_dir() -> Path:
    env_dir = os.getenv("TASK_ROUTER_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)

    current_file = Path(__file__).resolve()
    candidates = [
        Path.cwd() / "config",
        current_file.parents[1] / "config",
        current_file.parents[2] / "config",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return Path.cwd() / "config"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Route a free-text task to project, complexity, and workflow.")
    parser.add_argument("task", nargs="+", help="Task text in natural language.")
    parser.add_argument("--projects", type=Path, default=default_config_dir() / "projects.yml")
    parser.add_argument("--workflows", type=Path, default=default_config_dir() / "workflows.yml")
    parser.add_argument(
        "--provider",
        choices=["codex-cli", "openai-api", "mock"],
        default=None,
        help="LLM provider. Default: TASK_ROUTER_PROVIDER or codex-cli.",
    )
    parser.add_argument("--mock", action="store_true", help="Use local heuristic classifier instead of an LLM call.")
    args = parser.parse_args()

    load_dotenv()
    provider = args.provider
    if args.mock:
        provider = "mock"

    config = load_router_config(args.projects, args.workflows)
    app = build_graph(config, provider=provider)
    state = app.invoke({"input_text": " ".join(args.task)})
    print(json.dumps(state["result"].model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
