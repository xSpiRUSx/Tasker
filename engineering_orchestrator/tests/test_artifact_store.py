from engineering_orchestrator.services.artifact_store import ArtifactStore
from engineering_orchestrator.services.task_store import TaskStore


def test_artifact_write_read_hash_and_relative_path(tmp_path):
    task_store = TaskStore(tmp_path / "orchestrator.sqlite3")
    task = task_store.create_task("Fix login")
    artifact_store = ArtifactStore(tmp_path / "obsidian")

    task.artifacts_dir = artifact_store.create_task_folder(task, "Fix login")
    task_store.update_task(task)
    artifact = artifact_store.write_markdown(task, "todo", "Todo v1", "# Todo", version=1)
    task_store.add_artifact(artifact)

    assert artifact.relative_path.startswith(task.artifacts_dir)
    assert artifact_store.read_text(artifact).startswith("---")
    assert artifact_store.compute_hash(artifact) == artifact.content_hash


def test_manual_edit_detection(tmp_path):
    task_store = TaskStore(tmp_path / "orchestrator.sqlite3")
    task = task_store.create_task("Fix login")
    artifact_store = ArtifactStore(tmp_path / "obsidian")
    task.artifacts_dir = artifact_store.create_task_folder(task, "Fix login")
    artifact = artifact_store.write_markdown(task, "todo", "Todo v1", "# Todo", version=1)

    path = artifact_store.root_path / artifact.relative_path
    path.write_text(path.read_text(encoding="utf-8") + "\nManual edit\n", encoding="utf-8")

    assert artifact_store.compute_hash(artifact) != artifact.content_hash
