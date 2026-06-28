# Tasker

Tasker is an early Hermes-style engineering agent platform. It combines task
routing, workflow selection, approval gates, execution, validation, review, and
Markdown artifact storage for human-supervised development work.

The project is now a modular monolith:

- one installable Python application: `engineering-assistant`;
- one FastAPI app;
- one SQLite database;
- one Obsidian-compatible artifact root;
- one root `config` directory.

Internally it keeps clear module boundaries:

- `engineering_assistant` - the unified FastAPI and composition layer.
- `task_router` - classifies a free-text user request into project, intent,
  task kind, complexity, risk, tools, and workflow.
- `engineering_orchestrator` - manages the engineering task lifecycle: task
  creation, context artifacts, approval gates, execution, validation, review,
  and final reports.

Source packages live under `src/`:

```text
src/
  engineering_assistant/
  engineering_orchestrator/
  task_router/
tests/
  orchestrator/
  task_router/
  fixtures/
```

## Current Shape

```text
user request
  -> engineering_assistant FastAPI
  -> internal task_router
  -> RouteDecision
  -> engineering_orchestrator lifecycle
  -> Markdown task folder
  -> approval gates
  -> executor
  -> validation / review / final report
```

The orchestrator calls the router directly through an in-process Python
boundary. `/route` remains available as a debug endpoint, while `/tasks` is the
main lifecycle endpoint.

## Quick Start

```powershell
cd C:\Configuration\Tasker
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
uvicorn engineering_assistant.api:app --reload
```

The API starts on `http://127.0.0.1:8000`.

Configure local storage explicitly when needed:

```powershell
$env:ORCHESTRATOR_ARTIFACTS_ROOT = "D:\Obsidian\AI Engineering Tasks"
$env:ORCHESTRATOR_SQLITE_PATH = ".\data\orchestrator.sqlite3"
```

Debug route check:

```powershell
curl.exe -X POST http://127.0.0.1:8000/route `
  -H "Content-Type: application/json" `
  -d "{\"message\":\"Solvix_ZN: напиши простую обработку привет мир\"}"
```

Create a full lifecycle task:

```powershell
curl.exe -X POST http://127.0.0.1:8000/tasks `
  -H "Content-Type: application/json" `
  -d "{\"message\":\"Solvix_ZN: напиши простую обработку привет мир\",\"source\":\"cli\",\"user_id\":\"alexey\"}"
```

Approve the generated plan:

```powershell
curl.exe -X POST http://127.0.0.1:8000/tasks/ENG-2026-00001/approvals/plan `
  -H "Content-Type: application/json" `
  -d "{\"decision\":\"approve\"}"
```

Inspect task state, run trace, and events:

```powershell
curl.exe http://127.0.0.1:8000/tasks
curl.exe http://127.0.0.1:8000/tasks/ENG-2026-00001/context
curl.exe http://127.0.0.1:8000/tasks/ENG-2026-00001/runs
curl.exe http://127.0.0.1:8000/tasks/ENG-2026-00001/events
```

Open the configured artifact root in Obsidian as a vault or folder. Each task
gets its own Markdown folder with the route, context, working memory, plan,
validation, evaluation, review, diff, and final report artifacts.

## Configuration

The unified app uses YAML files under the root `config` directory:

- `config/projects.yml` - project registry, aliases, paths, and tools.
- `config/workflows.yml` - workflow eligibility, required gates, and steps.
- `config/orchestrator.yml` - storage, artifact, approval, router, execution,
  and validation settings.

For secrets and provider-specific settings, use environment variables or local
`.env` files. Do not commit credentials.

## Real Codex Execution

Planning uses the deterministic `mock` planner by default, so the MVP remains
usable even when Codex CLI is not installed or logged in. To generate plan
artifacts through Codex CLI, start the server with:

```powershell
$env:ORCHESTRATOR_PLANNER_PROVIDER = "codex-cli"
engineering-assistant --port 8001
```

If Codex planning fails, Tasker falls back to the mock planner and records a
planner warning in the approval artifact.

Execution is separate. By default the lifecycle uses the safe `mock` executor.
To let approved tasks create a git worktree and run Codex CLI there, start the
server with:

```powershell
$env:ORCHESTRATOR_DEFAULT_EXECUTOR = "codex"
engineering-assistant --port 8001
```

In `codex` mode, approving the `plan` gate will:

- create a git worktree under `data/worktrees`;
- run `codex exec` in that worktree using the approved task artifacts;
- write execution, validation, review, diff summary, and patch artifacts into
  the Obsidian task folder;
- request a separate `commit` approval after diff approval.

The selected `project_path` must be a git repository.

For risky routes, pre-execution gates such as `spec`, `config_change`,
`migration`, `security_change`, and `deploy_prep` are requested after plan
approval and before Codex execution.

Question-only routes close without plan, execution, diff, or commit approval
gates. They write `03-answer.md` and `13-final-report.md` into the task folder.

## Task Inbox

The API exposes a small approval inbox:

- `GET /tasks`
- `GET /tasks?status=awaiting_plan_approval`
- `GET /tasks?project_id=solvix_zn`
- `GET /tasks/{task_id}/approvals`
- `GET /tasks/{task_id}/events`
- `GET /tasks/{task_id}/context`
- `POST /tasks/{task_id}/rebuild-context`
- `GET /tasks/{task_id}/runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/steps`

## Clean Export

Use the export script when sharing or archiving the project:

```powershell
python .\scripts\create_source_archive.py --output .\dist\tasker-source.zip
```

The generated ZIP includes source, tests, config, docs, and project metadata.
It excludes runtime data such as `data/`, worktrees, SQLite databases, logs,
virtual environments, caches, build output, and generated archives.

## Recommended Roadmap

1. Add worktree cleanup after successful commit or task cancellation.
2. Introduce a confidence policy: auto-run low-risk tasks, ask clarifying
   questions for low confidence, require explicit approval for risky changes.
3. Replace route-metadata-only context collection with scoped source inspection
   before planning.
4. Add a real answer provider for `question_only` workflows.
5. Normalize task artifacts so `spec`, `todo`, `test_plan`, `review`, and
   `final_report` have stable schemas.

## Local Development Notes

- This workspace is Windows-first; use PowerShell commands.
- Use `python`, not `python3`.
- Keep generated runtime data out of source control: virtualenvs, pytest caches,
  SQLite databases, worktrees, and generated task artifacts.
- Prefer small, reviewable changes because this system is intended to make
  agent behavior inspectable.
