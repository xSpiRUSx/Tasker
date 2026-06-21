from __future__ import annotations

from engineering_orchestrator.models import Task, TaskEvent
from engineering_orchestrator.services.artifact_store import ArtifactStore
from engineering_orchestrator.services.task_store import TaskStore


class EventService:
    def __init__(self, task_store: TaskStore, artifact_store: ArtifactStore):
        self.task_store = task_store
        self.artifact_store = artifact_store

    def add(self, task: Task, event_type: str, payload: dict | None = None) -> TaskEvent:
        event = self.task_store.add_event(task.id, event_type, payload or {})
        artifact = self.artifact_store.append_event(task, event)
        self.task_store.add_artifact(artifact)
        return event
