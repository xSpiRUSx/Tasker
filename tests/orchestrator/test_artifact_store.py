from engineering_orchestrator.services.artifact_store import ArtifactStore
from engineering_orchestrator.services.event_service import EventService
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


def test_non_versioned_event_artifact_is_stable(tmp_path):
    task_store = TaskStore(tmp_path / "orchestrator.sqlite3")
    artifact_store = ArtifactStore(tmp_path / "obsidian")
    event_service = EventService(task_store, artifact_store)
    task = task_store.create_task("Fix login")
    task.artifacts_dir = artifact_store.create_task_folder(task, "Fix login")
    task_store.update_task(task)

    event_service.add(task, "first")
    event_service.add(task, "second")

    artifacts = [artifact for artifact in task_store.list_artifacts(task.id) if artifact.kind == "events"]
    assert len(artifacts) == 1
    assert "first" in artifact_store.read_text(artifacts[0])
    assert "second" in artifact_store.read_text(artifacts[0])


def test_task_folder_uses_short_slug_for_long_russian_text(tmp_path):
    task_store = TaskStore(tmp_path / "orchestrator.sqlite3")
    task = task_store.create_task(
        "Сделай очень длинную простую обработку привет мир для проверки короткого имени папки Obsidian"
    )
    task.project_id = "solvix_zn"
    artifact_store = ArtifactStore(tmp_path / "obsidian", "{task_id} - {project_id} - {slug_short}")

    folder = artifact_store.create_task_folder(task, task.user_message)

    assert task.id in folder
    assert "solvix_zn" in folder
    assert "#U" not in folder
    assert len(folder) < 90
