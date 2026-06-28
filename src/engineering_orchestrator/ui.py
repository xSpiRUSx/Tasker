from __future__ import annotations

from pathlib import Path
from html import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse


def register_ui_routes(app: FastAPI, orchestrator) -> None:
    templates = _load_templates()

    @app.get("/ui", include_in_schema=False)
    def ui_root():
        return RedirectResponse("/ui/tasks", status_code=303)

    @app.get("/ui/tasks", response_class=HTMLResponse, include_in_schema=False)
    def ui_tasks(request: Request, status: str | None = None):
        tasks = orchestrator.list_tasks(status)
        if templates is None:
            return HTMLResponse(_fallback_tasks_html(tasks, status or ""))
        return templates.TemplateResponse(
            "ui_tasks.html.j2",
            {
                "request": request,
                "tasks": tasks,
                "status": status or "",
            },
        )

    @app.get("/ui/tasks/{task_id}", response_class=HTMLResponse, include_in_schema=False)
    def ui_task(request: Request, task_id: str):
        try:
            task = orchestrator.get_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        artifacts = orchestrator.list_artifacts(task_id)
        approvals = orchestrator.list_approvals(task_id)
        events = orchestrator.list_events(task_id)
        pending = [approval for approval in approvals if approval.status == "pending"]
        if templates is None:
            return HTMLResponse(_fallback_task_html(task, artifacts, approvals, events, pending))
        return templates.TemplateResponse(
            "ui_task.html.j2",
            {
                "request": request,
                "task": task,
                "artifacts": artifacts,
                "approvals": approvals,
                "events": events,
                "pending": pending,
            },
        )


def _load_templates():
    try:
        from fastapi.templating import Jinja2Templates
    except ImportError:
        return None
    return Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _fallback_tasks_html(tasks, status: str) -> str:
    rows = "\n".join(
        f"<tr><td><a href='/ui/tasks/{escape(task.id)}'><code>{escape(task.id)}</code></a></td>"
        f"<td><code>{escape(task.status)}</code></td>"
        f"<td><code>{escape(task.project_id or 'unknown')}</code></td>"
        f"<td>{escape(task.user_message)}</td></tr>"
        for task in tasks
    ) or "<tr><td colspan='4'>No tasks.</td></tr>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Tasker Tasks</title></head>
<body>
<h1>Tasker</h1>
<form method="get" action="/ui/tasks"><input name="status" value="{escape(status)}"><button type="submit">Filter</button></form>
<table>{rows}</table>
</body></html>"""


def _fallback_task_html(task, artifacts, approvals, events, pending) -> str:
    artifact_rows = "\n".join(
        f"<tr><td><code>{escape(artifact.kind)}</code></td><td>{escape(artifact.title)}</td>"
        f"<td>{artifact.version or ''}</td><td><code>{escape(artifact.relative_path)}</code></td></tr>"
        for artifact in artifacts
    ) or "<tr><td colspan='4'>No artifacts.</td></tr>"
    event_rows = "\n".join(
        f"<tr><td>{escape(str(event.created_at))}</td><td><code>{escape(event.event_type)}</code></td>"
        f"<td><code>{escape(str(event.payload))}</code></td></tr>"
        for event in events
    ) or "<tr><td colspan='3'>No events.</td></tr>"
    pending_text = ", ".join(escape(approval.gate) for approval in pending) or "None."
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{escape(task.id)}</title></head>
<body>
<a href="/ui/tasks">Tasks</a>
<h1><code>{escape(task.id)}</code></h1>
<p>Status: <code>{escape(task.status)}</code></p>
<p>Project: <code>{escape(task.project_id or 'unknown')}</code></p>
<p>Workflow: <code>{escape(task.workflow_id or 'unknown')}</code></p>
<p>{escape(task.user_message)}</p>
<h2>Pending Approvals</h2><p>{pending_text}</p>
<h2>Artifacts</h2><table>{artifact_rows}</table>
<h2>Events</h2><table>{event_rows}</table>
</body></html>"""
