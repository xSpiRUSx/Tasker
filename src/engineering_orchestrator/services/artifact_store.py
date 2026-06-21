from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

from engineering_orchestrator.models import ArtifactKind, Task, TaskArtifact, TaskEvent
from engineering_orchestrator.services.task_store import utc_now


FILENAME_BY_KIND: dict[str, str] = {
    "task_index": "00-task.md",
    "request": "00-request.md",
    "route_decision": "01-route.md",
    "context_summary": "02-context.md",
    "spec": "03-spec.v{version}.md",
    "todo": "04-todo.v{version}.md",
    "test_plan": "05-test-plan.v{version}.md",
    "approval_request": "06-approval-plan.v{version}.md",
    "execution_log": "07-execution.md",
    "validation_report": "08-validation.md",
    "review_report": "09-review.md",
    "diff_summary": "10-diff-summary.md",
    "diff_patch": "10-diff.patch",
    "commit_message": "11-commit.md",
    "commit_result": "11-commit-result.md",
    "deploy_plan": "12-deploy-plan.md",
    "rollback_plan": "12-rollback-plan.md",
    "final_report": "13-final-report.md",
    "events": "events.md",
}


def slugify(value: str, fallback: str = "task") -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9а-яё]+", "-", value, flags=re.IGNORECASE).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:80] or fallback


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArtifactStore:
    def __init__(self, root_path: str | Path, task_folder_template: str = "{task_id} - {project_id} {slug}"):
        self.root_path = Path(root_path)
        self.task_folder_template = task_folder_template
        self.root_path.mkdir(parents=True, exist_ok=True)

    def create_task_folder(self, task: Task, slug: str) -> str:
        folder_name = self.task_folder_template.format(
            task_id=task.id,
            project_id=task.project_id or "unrouted",
            slug=slugify(slug),
        ).strip()
        folder = self.root_path / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        return folder_name

    def write_markdown(
        self,
        task: Task,
        kind: ArtifactKind,
        title: str,
        content: str,
        version: int | None = None,
        filename: str | None = None,
        frontmatter: dict[str, Any] | None = None,
        include_frontmatter: bool = True,
    ) -> TaskArtifact:
        if not task.artifacts_dir:
            raise ValueError("Task artifacts_dir must be set before writing artifacts.")

        name = filename or FILENAME_BY_KIND[kind].format(version=version or 1)
        path = self.root_path / task.artifacts_dir / name
        if version is not None and path.exists():
            raise FileExistsError(f"Versioned artifact already exists: {path}")

        path.parent.mkdir(parents=True, exist_ok=True)
        full_text = self._with_frontmatter(task, kind, version, content, frontmatter) if include_frontmatter else content.rstrip() + "\n"
        self._atomic_write(path, full_text)
        relative_path = path.relative_to(self.root_path).as_posix()
        now = utc_now()
        return TaskArtifact(
            id=f"artifact-{uuid.uuid4().hex[:12]}",
            task_id=task.id,
            kind=kind,
            version=version,
            title=title,
            relative_path=relative_path,
            content_hash=sha256_text(full_text),
            created_at=now,
            updated_at=now,
        )

    def read_text(self, artifact: TaskArtifact) -> str:
        return (self.root_path / artifact.relative_path).read_text(encoding="utf-8")

    def compute_hash(self, artifact: TaskArtifact) -> str:
        return sha256_text(self.read_text(artifact))

    def update_task_index(
        self,
        task: Task,
        artifacts: list[TaskArtifact] | None = None,
        current_approval_summary: str = "No pending approval.",
    ) -> TaskArtifact:
        artifact_lines = []
        for artifact in artifacts or []:
            label = artifact.title
            target = Path(artifact.relative_path).name
            artifact_lines.append(f"- [[{target}|{label}]]")
        if not artifact_lines:
            artifact_lines.append("- No artifacts yet.")

        content = f"""# {task.id} - {self._title_from_task(task)}

## Status

`{task.status}`

## Original request

> {task.user_message}

## Routing

- Project: `{task.project_id or "unknown"}`
- Workflow: `{task.workflow_id or "unknown"}`
- Risk: `{task.risk_level or "unknown"}`

## Artifacts

{chr(10).join(artifact_lines)}

## Current approval

{current_approval_summary}

## Events

See [[events]].
"""
        return self.write_markdown(
            task,
            "task_index",
            "Task index",
            content,
            filename="00-task.md",
            frontmatter={"branch": task.branch_name},
        )

    def append_event(self, task: Task, event: TaskEvent) -> TaskArtifact:
        existing = ""
        path = self.root_path / (task.artifacts_dir or "") / "events.md"
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing.startswith("---"):
                parts = existing.split("---", 2)
                existing = parts[2].lstrip() if len(parts) == 3 else existing
        line = f"- `{event.created_at.isoformat()}` **{event.event_type}** {event.payload}\n"
        content = (existing.rstrip() + "\n" if existing else "# Events\n\n") + line
        return self.write_markdown(task, "events", "Events", content, filename="events.md")

    def _with_frontmatter(
        self,
        task: Task,
        kind: ArtifactKind,
        version: int | None,
        content: str,
        extra: dict[str, Any] | None,
    ) -> str:
        data: dict[str, Any] = {
            "task_id": task.id,
            "kind": kind,
            "version": version,
            "status": task.status,
            "project_id": task.project_id,
            "workflow_id": task.workflow_id,
            "risk_level": task.risk_level,
            "created_at": utc_now().isoformat(),
            "tags": [
                "ai-task",
                f"ai-task/status/{task.status.replace('_', '-')}",
                f"ai-task/project/{task.project_id or 'unknown'}",
                f"ai-task/workflow/{task.workflow_id or 'unknown'}",
            ],
        }
        if extra:
            data.update(extra)

        lines = ["---"]
        for key, value in data.items():
            lines.extend(self._yaml_lines(key, value))
        lines.append("---")
        lines.append("")
        lines.append(content.rstrip())
        lines.append("")
        return "\n".join(lines)

    def _yaml_lines(self, key: str, value: Any) -> list[str]:
        if isinstance(value, list):
            lines = [f"{key}:"]
            lines.extend(f"  - {item}" for item in value)
            return lines
        if value is None:
            return [f"{key}: null"]
        escaped = str(value).replace('"', '\\"')
        return [f'{key}: "{escaped}"']

    def _atomic_write(self, path: Path, text: str) -> None:
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_text(text, encoding="utf-8", newline="\n")
        temp_path.replace(path)

    def _title_from_task(self, task: Task) -> str:
        return task.user_message.splitlines()[0][:100]
