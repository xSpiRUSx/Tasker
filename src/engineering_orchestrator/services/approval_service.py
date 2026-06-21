from __future__ import annotations

from engineering_orchestrator.models import Approval
from engineering_orchestrator.services.artifact_store import ArtifactStore
from engineering_orchestrator.services.task_store import TaskStore


class ApprovalService:
    def __init__(self, task_store: TaskStore, artifact_store: ArtifactStore):
        self.task_store = task_store
        self.artifact_store = artifact_store

    def refresh_artifact_hashes(self, approval: Approval) -> list[str]:
        changed: list[str] = []
        for artifact_id in approval.artifact_ids:
            artifact = next((item for item in self.task_store.list_artifacts(approval.task_id) if item.id == artifact_id), None)
            if artifact is None:
                continue
            current_hash = self.artifact_store.compute_hash(artifact)
            if current_hash != artifact.content_hash:
                artifact.content_hash = current_hash
                self.task_store.update_artifact(artifact)
                changed.append(artifact.id)
        return changed
