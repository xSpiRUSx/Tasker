from engineering_orchestrator.services.task_store import TaskStore


def test_task_store_create_and_retrieve_task(tmp_path):
    store = TaskStore(tmp_path / "orchestrator.sqlite3")

    task = store.create_task("Fix login", source="test", user_id="u1", prefix="ENG")
    loaded = store.get_task(task.id)

    assert loaded.id.startswith("ENG-")
    assert loaded.status == "created"
    assert loaded.user_message == "Fix login"


def test_events_are_chronological(tmp_path):
    store = TaskStore(tmp_path / "orchestrator.sqlite3")
    task = store.create_task("Fix login")

    store.add_event(task.id, "first")
    store.add_event(task.id, "second")

    assert [event.event_type for event in store.list_events(task.id)] == ["first", "second"]


def test_approval_create_and_resolve(tmp_path):
    store = TaskStore(tmp_path / "orchestrator.sqlite3")
    task = store.create_task("Fix login")
    approval = store.create_approval(task.id, "plan", [])

    assert store.get_pending_approval(task.id, "plan") is not None
    resolved = store.resolve_approval(approval.id, "approved")

    assert resolved.status == "approved"
    assert store.get_pending_approval(task.id, "plan") is None
