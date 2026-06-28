# Hermes/OpenClaw Tasker Skill

This document describes the stable Tasker operations for local agents.

## Core Commands

```powershell
tasker route "Solvix_ZN: implement a small report"
tasker task create "Solvix_ZN: implement a small report"
tasker task show ENG-2026-00001
tasker task artifacts ENG-2026-00001
tasker task approvals ENG-2026-00001
tasker task events ENG-2026-00001
tasker task open ENG-2026-00001
tasker task approve ENG-2026-00001 plan
tasker task reject ENG-2026-00001 plan "Clarify affected files"
```

## API Operations

- `POST /tasks` creates a routed task and advances it to the nearest approval gate.
- `GET /tasks?status=awaiting_plan_approval` lists approval inbox items.
- `GET /tasks/{task_id}/approvals` lists gate decisions.
- `GET /tasks/{task_id}/events` lists lifecycle events.
- `POST /tasks/{task_id}/approvals/{gate}` approves or rejects a gate.
- `POST /tasks/{task_id}/messages` adds a correction and creates a revised plan when the task is rejected or needs changes.

## UI

- `/ui/tasks` shows the local task inbox.
- `/ui/tasks/{task_id}` shows status, artifacts, events, and approval actions.

## Safety Contract

- Plan approval is required before execution.
- Diff approval is not requested when execution, validation, or policy checks fail.
- Codex execution receives an executor policy artifact with blocked paths and diff limits.
- Commit approval remains separate from diff approval when the workflow requires it.
