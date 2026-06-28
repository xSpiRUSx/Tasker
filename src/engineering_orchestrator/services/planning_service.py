from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from engineering_orchestrator.models import RouteDecision, Task


class PlanDraft(BaseModel):
    spec_markdown: str = Field(description="Specification Markdown. Empty string when no spec is needed.")
    todo_markdown: str = Field(description="Implementation todo Markdown.")
    test_plan_markdown: str = Field(description="Validation and regression test plan Markdown.")
    approval_markdown: str = Field(description="Plan approval request Markdown.")
    planning_notes: str = Field(description="Short notes about how the plan was produced.")


class PlanWriter(Protocol):
    def write_plan(self, task: Task, route: RouteDecision, context_markdown: str) -> PlanDraft:
        ...


class MockPlanWriter:
    def write_plan(self, task: Task, route: RouteDecision, context_markdown: str) -> PlanDraft:
        spec_markdown = ""
        if route.requires_spec:
            spec_markdown = f"""# Specification

## Goal

Resolve the requested task for `{task.project_id}`: {task.user_message}

## Non-goals

- Production deploy.
- Secret changes.
- Destructive database migrations.
- Source modification before required approvals.

## Affected areas

- Project: `{task.project_id}`
- Workflow: `{task.workflow_id}`
- Risk flags: `{", ".join(route.risk_flags) or "none"}`

## Acceptance criteria

- Required approvals are collected before execution.
- Configured execution produces execution, validation, and review artifacts.
- Diff approval is requested before closing.

## Risks

{_bullet_list(route.risk_flags or ["No specific risk flags detected by router."])}

## Approval gates

{_bullet_list(route.approval_gates)}
"""

        return PlanDraft(
            spec_markdown=spec_markdown,
            todo_markdown=f"""# Todo

- [ ] Collect relevant context for `{task.project_id}`.
- [ ] Identify affected files.
- [ ] Implement approved change.
- [ ] Add or update tests.
- [ ] Run validation.
- [ ] Prepare review report.
""",
            test_plan_markdown=f"""# Test plan

## Automated checks

- Use configured project test commands when real execution is enabled.
- Mock validation records a pass without running project commands.

## Manual checks

- Open generated Markdown artifacts in Obsidian.
- Confirm approval gates match the selected workflow.

## Regression expectations

- The original request should be covered by implementation notes before real execution is enabled.

## Risk-specific tests

- Risk level: `{task.risk_level}`
- Add focused tests for risky areas before enabling real commits.
""",
            approval_markdown="""# Approval request

Approving this plan allows the agent to:

- Create a task branch/worktree when real git execution is enabled.
- Modify source/test files according to the plan when real execution is enabled.
- Run configured validation commands.
- Produce a diff for review.

This approval does not allow:

- Direct production deploy.
- Secret changes.
- Destructive database migrations.
- Commit without final diff approval.
""",
            planning_notes="Mock planner used deterministic templates.",
        )


class CodexPlanWriter:
    def __init__(
        self,
        codex_bin: str = "codex",
        model: str | None = None,
        timeout_seconds: int = 900,
    ):
        self.codex_bin = codex_bin
        self.model = model
        self.timeout_seconds = timeout_seconds

    def write_plan(self, task: Task, route: RouteDecision, context_markdown: str) -> PlanDraft:
        schema = _strict_json_schema(PlanDraft.model_json_schema())
        with tempfile.TemporaryDirectory(prefix="tasker-plan-codex-") as tmp:
            schema_path = Path(tmp) / "plan.schema.json"
            schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")

            command = [self._resolve_codex_bin(), "exec", "-", "--output-schema", str(schema_path), "--skip-git-repo-check"]
            if self.model:
                command.extend(["--model", self.model])

            completed = subprocess.run(
                self._windows_command(command),
                cwd=self._working_directory(task),
                input=self._build_prompt(task, route, context_markdown),
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )

        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise RuntimeError(
                "Codex CLI planning failed. Run `codex login` first and retry."
                + (f"\n\nCodex stderr:\n{stderr}" if stderr else "")
            )

        payload = _extract_json_object(completed.stdout)
        return PlanDraft.model_validate(payload)

    def _build_prompt(self, task: Task, route: RouteDecision, context_markdown: str) -> str:
        return f"""
You are a senior engineering planner. Produce a concrete implementation plan for an approved-by-human workflow.

You must not modify files. Only inspect and reason if needed.

Return Markdown strings in the requested JSON schema.

Planning requirements:
- Make the plan specific to the task and project.
- Identify likely files or metadata areas when possible.
- For 1C/configuration changes, call out configuration approval and risk.
- Keep todo items actionable and ordered.
- Include validation checks and manual review steps.
- Do not claim that execution has happened.
- Do not include hidden chain-of-thought.

Task:
- ID: {task.id}
- Request: {task.user_message}
- Project: {task.project_id} / {task.project_name}
- Project path: {task.project_path}
- Workflow: {task.workflow_id} / {task.workflow_name}
- Risk: {task.risk_level}

Route decision:
```json
{json.dumps(route.model_dump(), ensure_ascii=False, indent=2)}
```

Context artifact:
```markdown
{context_markdown}
```
""".strip()

    def _working_directory(self, task: Task) -> Path:
        if task.project_path:
            path = Path(task.project_path)
            if path.exists():
                return path
        return Path.cwd()

    def _resolve_codex_bin(self) -> str:
        return shutil.which(self.codex_bin) or self.codex_bin

    def _windows_command(self, command: list[str]) -> list[str]:
        if os.name != "nt":
            return command
        suffix = Path(command[0]).suffix.lower()
        if suffix in {".cmd", ".bat"}:
            return ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(command)]
        return command


class PlanningService:
    def __init__(
        self,
        provider: str = "mock",
        codex_bin: str = "codex",
        model: str | None = None,
        timeout_seconds: int = 900,
    ):
        self.provider = provider
        if provider == "codex-cli":
            self.writer: PlanWriter = CodexPlanWriter(codex_bin, model=model, timeout_seconds=timeout_seconds)
        else:
            self.writer = MockPlanWriter()

    def write_plan(self, task: Task, route: RouteDecision, context_markdown: str) -> PlanDraft:
        try:
            return self.writer.write_plan(task, route, context_markdown)
        except Exception as exc:
            if self.provider != "codex-cli":
                raise
            draft = MockPlanWriter().write_plan(task, route, context_markdown)
            draft.planning_notes = (
                "Codex CLI planning failed; deterministic mock planner fallback was used. "
                f"Error: {exc}"
            )
            draft.approval_markdown = (
                draft.approval_markdown.rstrip()
                + "\n\n## Planner warning\n\n"
                + "Codex CLI planning failed, so this approval request was generated by the mock planner fallback.\n"
            )
            return draft


def _bullet_list(values: list[str]) -> str:
    if not values:
        return "- None."
    return "\n".join(f"- {value}" for value in values)


def _strict_json_schema(schema: dict) -> dict:
    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties.keys())
                node["additionalProperties"] = False
                for child in properties.values():
                    visit(child)
            for key in ("$defs", "definitions"):
                values = node.get(key)
                if isinstance(values, dict):
                    for child in values.values():
                        visit(child)
            for key in ("anyOf", "oneOf", "allOf"):
                values = node.get(key)
                if isinstance(values, list):
                    for child in values:
                        visit(child)
            if isinstance(node.get("items"), dict):
                visit(node["items"])
        elif isinstance(node, list):
            for item in node:
                visit(item)
        return node

    return visit(json.loads(json.dumps(schema)))


def _extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if not stripped:
        raise RuntimeError("Codex CLI returned an empty planning response.")

    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError(f"Codex CLI did not return a JSON object:\n{stripped}")

    value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise RuntimeError("Codex CLI returned JSON, but it was not an object.")
    return value
