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


def test_model_calls_are_listed_with_total_tokens(tmp_path):
    store = TaskStore(tmp_path / "orchestrator.sqlite3")
    task = store.create_task("Fix login")

    record = store.add_model_call(
        task.id,
        "run-1",
        "execute_code",
        "codex_cli",
        "gpt-5.5",
        provider="codex-estimated",
        reasoning_effort="medium",
        prompt_chars=1200,
        prompt_tokens=300,
        completion_tokens=40,
        cached_prompt_tokens=120,
        reasoning_tokens=10,
        total_tokens=340,
        usage_source="test_usage",
        usage_is_estimated=False,
        cost_usd=0.0123,
        latency_ms=1500,
        status="success",
    )

    items = store.list_model_calls(task.id)

    assert [item.id for item in items] == [record.id]
    assert items[0].model == "gpt-5.5"
    assert items[0].total_tokens == 340
    assert items[0].cached_prompt_tokens == 120
    assert items[0].reasoning_tokens == 10
    assert items[0].usage_source == "test_usage"
    assert items[0].usage_is_estimated is False
    assert items[0].cost_usd == 0.0123


def test_approval_create_and_resolve(tmp_path):
    store = TaskStore(tmp_path / "orchestrator.sqlite3")
    task = store.create_task("Fix login")
    approval = store.create_approval(task.id, "plan", [])

    assert store.get_pending_approval(task.id, "plan") is not None
    resolved = store.resolve_approval(approval.id, "approved")

    assert resolved.status == "approved"
    assert store.get_pending_approval(task.id, "plan") is None
