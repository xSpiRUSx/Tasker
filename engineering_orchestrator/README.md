# engineering_orchestrator

MVP application for managing engineering task lifecycle:

1. Create and route a task.
2. Write human-readable Markdown artifacts into an Obsidian-compatible folder.
3. Request plan approval.
4. Run mock execution, validation, and review.
5. Request diff approval.
6. Close the task with commit skipped for MVP.

State is stored in SQLite. Artifacts are stored as Markdown files under `data/obsidian-tasks` by default.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[test]
python -m pytest
python -m engineering_orchestrator.main
```

The API starts on `http://127.0.0.1:8000`.

## Example

```powershell
curl.exe -X POST http://127.0.0.1:8000/tasks `
  -H "Content-Type: application/json" `
  -d "{\"message\":\"Login fails in billing-api after config update\",\"source\":\"cli\",\"user_id\":\"alexey\"}"
```

Then approve the generated plan:

```powershell
curl.exe -X POST http://127.0.0.1:8000/tasks/ENG-2026-00001/approvals/plan `
  -H "Content-Type: application/json" `
  -d "{\"decision\":\"approve\"}"
```

Approve the mock diff:

```powershell
curl.exe -X POST http://127.0.0.1:8000/tasks/ENG-2026-00001/approvals/diff `
  -H "Content-Type: application/json" `
  -d "{\"decision\":\"approve\"}"
```
