from __future__ import annotations

import hashlib
import json
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
    "working_memory": "02-working-memory.md",
    "working_memory_json": "02-working-memory.json",
    "model_decisions": "02-model-decisions.md",
    "model_decisions_json": "02-model-decisions.json",
    "prompt_manifest": "02-prompt-manifest.md",
    "tool_health_report": "02-tool-health.md",
    "context_compact": "02-context-compact.md",
    "context_compact_json": "02-context-compact.json",
    "answer": "03-answer.md",
    "spec": "03-spec.v{version}.md",
    "todo": "04-todo.v{version}.md",
    "test_plan": "05-test-plan.v{version}.md",
    "approval_request": "06-approval-plan.v{version}.md",
    "execution_log": "07-execution.md",
    "executor_policy": "07-executor-policy.md",
    "executor_prompt": "07-executor-prompt.md",
    "executor_command": "07-executor-command.md",
    "executor_stdout": "07-executor-stdout.md",
    "executor_stderr": "07-executor-stderr.md",
    "validation_report": "08-validation.md",
    "validation_command_output": "08-validation-command-{version}.md",
    "policy_report": "09-policy.md",
    "run_report": "07-run.md",
    "run_report_json": "07-run.json",
    "evaluation_report": "08-evaluation.md",
    "repair_prompt": "08-repair-prompt.md",
    "correction_request": "12-correction-{version:03d}.md",
    "correction_context": "12-correction-{version:03d}-context.md",
    "correction_result": "12-correction-{version:03d}-result.md",
    "spec_addendum": "03-spec.addendum.v{version}.md",
    "diagnosis": "09-diagnosis.md",
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


NON_VERSIONED_ARTIFACT_KINDS: set[str] = {
    "task_index",
    "request",
    "route_decision",
    "context_summary",
    "working_memory",
    "working_memory_json",
    "model_decisions",
    "model_decisions_json",
    "prompt_manifest",
    "tool_health_report",
    "context_compact",
    "context_compact_json",
    "answer",
    "execution_log",
    "executor_policy",
    "executor_prompt",
    "executor_command",
    "executor_stdout",
    "executor_stderr",
    "validation_report",
    "policy_report",
    "run_report",
    "run_report_json",
    "evaluation_report",
    "repair_prompt",
    "diagnosis",
    "review_report",
    "diff_summary",
    "diff_patch",
    "commit_message",
    "commit_result",
    "deploy_plan",
    "rollback_plan",
    "final_report",
    "events",
}


def slugify(value: str, fallback: str = "task") -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9а-яё]+", "-", value, flags=re.IGNORECASE).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:80] or fallback


def slugify_short(value: str, fallback: str = "task", max_prefix: int = 46, hash_length: int = 5) -> str:
    slug = slugify(value, fallback=fallback)
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:hash_length]
    if len(slug) <= max_prefix:
        return f"{slug}-{digest}"
    return f"{slug[:max_prefix].rstrip('-')}-{digest}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArtifactStore:
    def __init__(self, root_path: str | Path, task_folder_template: str = "{task_id} - {project_id} - {slug_short}"):
        self.root_path = Path(root_path)
        self.task_folder_template = task_folder_template
        self.root_path.mkdir(parents=True, exist_ok=True)

    def create_task_folder(self, task: Task, slug: str) -> str:
        folder_name = self.task_folder_template.format(
            task_id=task.id,
            project_id=task.project_id or "unrouted",
            slug=slugify(slug),
            slug_short=slugify_short(slug),
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

    def write_json(
        self,
        task: Task,
        kind: ArtifactKind,
        title: str,
        payload: dict[str, Any] | list[Any],
        filename: str | None = None,
    ) -> TaskArtifact:
        content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        artifact = self.write_markdown(
            task,
            kind,
            title,
            content,
            filename=filename,
            include_frontmatter=False,
        )
        artifact.content_type = "application/json"
        return artifact

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
        seen: set[tuple[str, str, int | None]] = set()
        for artifact in artifacts or []:
            if artifact.kind == "task_index":
                continue
            label = artifact.title
            target = Path(artifact.relative_path).name
            key = (artifact.kind, target, artifact.version)
            if key in seen:
                continue
            seen.add(key)
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
        path = self.root_path / (task.artifacts_dir or "") / "events.md"
        event_lines: list[str] = []
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing.startswith("---"):
                parts = existing.split("---", 2)
                existing = parts[2].lstrip() if len(parts) == 3 else existing
            event_lines = [line for line in existing.splitlines() if line.startswith("- `")]
        line = f"- `{event.created_at.isoformat()}` **{event.event_type}** {event.payload}\n"
        event_lines.append(line.rstrip())
        omitted = max(0, len(event_lines) - 50)
        event_lines = event_lines[-50:]
        summary = f"_Showing latest 50 events. {omitted} older event(s) are stored in SQLite._\n\n" if omitted else ""
        content = "# Events\n\n" + summary + "\n".join(event_lines) + "\n"
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
