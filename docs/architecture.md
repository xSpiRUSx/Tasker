# Architecture

Tasker is organized as a modular monolith. There is one application process, but
the router and orchestrator remain separated by a small Python interface.

Runtime packages use `src` layout:

```text
src/
  engineering_assistant/
  engineering_orchestrator/
  task_router/
```

## Components

### `engineering_assistant`

The composition layer owns the single FastAPI app.

Endpoints:

- `POST /route` - debug/test endpoint for routing only.
- `POST /tasks` - full orchestration lifecycle.
- `GET /tasks/{task_id}` and artifact/approval endpoints.

### `task_router`

The router is responsible for deciding what the user is asking for.

Inputs:

- raw user message;
- `config/projects.yml`;
- `config/workflows.yml`;
- selected provider: `mock`, `codex-cli`, or `openai-api`.

Output:

- `RouteDecision`, including project, workflow, confidence, complexity, risk,
  approval gates, tool recommendations, missing information, assumptions, and
  next steps.

### `engineering_orchestrator`

The orchestrator is responsible for making the task durable and reviewable.

Inputs:

- user message;
- route decision from `task_router`;
- storage settings;
- executor settings;
- approval policy.

Outputs:

- task row in SQLite;
- Obsidian-compatible Markdown artifact folder;
- event log;
- approval records;
- execution, validation, review, diff, commit, and final report artifacts.

## Integration Boundary

The orchestrator receives a router object with one method:

```text
TaskRouter.route(message)
  -> RouteDecision
```

That keeps classification details out of the lifecycle code. Today the adapter
is in-process; later it can move to HTTP or a queue if the router becomes an
independent service.

## Execution

The executor is selected by `execution.default_executor` or
`ORCHESTRATOR_DEFAULT_EXECUTOR`.

- `mock` records lifecycle artifacts without changing project files.
- `codex` creates a git worktree, runs `codex exec` inside it, records changed
  files, and writes diff artifacts for review.

Pre-execution gates such as `spec`, `config_change`, `migration`,
`security_change`, and `deploy_prep` block execution until approved.

Diff approval requests a separate `commit` gate. Commit approval creates a git
commit in the task worktree when a worktree exists, then closes the task.

## Policy Model

The product should separate decision-making from permission:

- router decides what the task appears to be;
- confidence policy decides whether to ask questions or continue;
- workflow policy decides which artifacts and approval gates are required;
- executor policy decides which tools are allowed to make changes.

This keeps the agent useful without making it opaque.

## Artifact Contract

Stable artifact kinds should be treated as product API:

- `task_index`
- `route_decision`
- `context_summary`
- `spec`
- `todo`
- `test_plan`
- `approval_request`
- `execution_log`
- `validation_report`
- `review_report`
- `diff_summary`
- `commit_result`
- `final_report`

Future UI, Obsidian views, and automation should depend on these kinds rather
than guessing filenames.
