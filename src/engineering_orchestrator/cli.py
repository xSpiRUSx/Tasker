from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from engineering_assistant.task_router import TaskRouter
from engineering_orchestrator.api import Orchestrator
from engineering_orchestrator.models import ApprovalDecisionRequest, CreateTaskRequest
from engineering_orchestrator.settings import load_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tasker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    route_parser = subparsers.add_parser("route")
    route_parser.add_argument("message")

    task_parser = subparsers.add_parser("task")
    task_subparsers = task_parser.add_subparsers(dest="task_command", required=True)

    create_parser = task_subparsers.add_parser("create")
    create_parser.add_argument("message")
    create_parser.add_argument("--source", default="cli")
    create_parser.add_argument("--user-id")

    show_parser = task_subparsers.add_parser("show")
    show_parser.add_argument("task_id")

    artifacts_parser = task_subparsers.add_parser("artifacts")
    artifacts_parser.add_argument("task_id")

    approvals_parser = task_subparsers.add_parser("approvals")
    approvals_parser.add_argument("task_id")

    events_parser = task_subparsers.add_parser("events")
    events_parser.add_argument("task_id")

    open_parser = task_subparsers.add_parser("open")
    open_parser.add_argument("task_id")

    approve_parser = task_subparsers.add_parser("approve")
    approve_parser.add_argument("task_id")
    approve_parser.add_argument("gate")
    approve_parser.add_argument("comment", nargs="?")

    reject_parser = task_subparsers.add_parser("reject")
    reject_parser.add_argument("task_id")
    reject_parser.add_argument("gate")
    reject_parser.add_argument("comment")

    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "route":
        router = TaskRouter(settings.projects_path, settings.workflows_path, provider=settings.router_provider)
        _print(router.route(args.message))
        return

    orchestrator = Orchestrator(settings)
    if args.task_command == "create":
        _print(orchestrator.create_task(CreateTaskRequest(message=args.message, source=args.source, user_id=args.user_id)))
    elif args.task_command == "show":
        _print(orchestrator.get_task(args.task_id))
    elif args.task_command == "artifacts":
        _print(orchestrator.list_artifacts(args.task_id))
    elif args.task_command == "approvals":
        _print(orchestrator.list_approvals(args.task_id))
    elif args.task_command == "events":
        _print(orchestrator.list_events(args.task_id))
    elif args.task_command == "open":
        _open_task(orchestrator, args.task_id)
    elif args.task_command == "approve":
        _print(
            orchestrator.decide_approval(
                args.task_id,
                args.gate,
                ApprovalDecisionRequest(decision="approve", comment=args.comment),
            )
        )
    elif args.task_command == "reject":
        _print(
            orchestrator.decide_approval(
                args.task_id,
                args.gate,
                ApprovalDecisionRequest(decision="reject", comment=args.comment),
            )
        )


def _open_task(orchestrator: Orchestrator, task_id: str) -> None:
    artifact = orchestrator.task_store.get_artifact(task_id, "task_index")
    if artifact is None:
        raise SystemExit(f"Task index artifact was not found for {task_id}.")
    path = orchestrator.artifact_store.root_path / artifact.relative_path
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        opener = "open" if sys_platform() == "darwin" else "xdg-open"
        subprocess.run([opener, str(path)], check=False)
    print(path)


def sys_platform() -> str:
    import sys

    return sys.platform


def _print(value: Any) -> None:
    if isinstance(value, list):
        payload = [_to_jsonable(item) for item in value]
    else:
        payload = _to_jsonable(value)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    return value


if __name__ == "__main__":
    main()
