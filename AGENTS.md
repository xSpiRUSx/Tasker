# AGENTS.md

## Project Mission

Tasker is a Hermes-style engineering agent platform. The goal is to turn a
natural-language development request into a routed, reviewable, approved, and
validated engineering task.

The project is a modular monolith:

- `engineering_assistant` composes the unified FastAPI app.
- `task_router` routes user text to project, workflow, risk, tools, and next
  steps.
- `engineering_orchestrator` owns the task lifecycle, approvals, artifacts,
  execution, validation, review, and closure.

Runtime source packages live under `src/`; tests and test fixtures live under
`tests/`.

## Environment

- Work through PowerShell on Windows.
- Use `python`, not `python3`.
- Prefer absolute paths when invoking reusable user-level scripts.
- Do not copy credentials into project files. Use environment variables,
  `.env` files that stay local, or existing Codex auth/config mechanisms.

## Engineering Rules

- Read the local code and configuration before changing behavior.
- Preserve internal module boundaries inside the monolith unless a task
  explicitly asks for a deeper refactor.
- Prefer YAML-driven configuration for projects, workflows, tools, approval
  gates, and risk policy.
- Keep the agent lifecycle inspectable: every automated decision should be
  reproducible from stored route data, artifacts, events, or logs.
- Keep mock implementations available for tests even after adding real
  executors or router adapters.
- Avoid destructive operations against configured project paths, generated
  worktrees, or task artifacts unless the user explicitly asks for cleanup.

## Testing

Prefer running tests from the repository root:

```powershell
cd C:\Configuration\Tasker
python -m pytest
```

The root test command includes unified app tests plus router and orchestrator
module tests.

## Architecture Direction

The intended integration path is:

```text
free-text task
  -> engineering_assistant FastAPI
  -> internal router RouteDecision
  -> orchestrator task record
  -> Markdown artifacts
  -> approval gates
  -> executor
  -> validation and review
  -> final report
```

Do not bypass approval gates when implementing real executors. Low-risk
automation can be added later through explicit confidence and policy settings.
