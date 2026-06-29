from pathlib import Path

from fastapi.testclient import TestClient

from engineering_orchestrator.api import Orchestrator, create_app
from engineering_orchestrator.models import CreateTaskRequest
from engineering_orchestrator.settings import Settings
from task_router.adaptive.cheap_classifier import build_classifier_prompt
from task_router.adaptive.config import CheapClassifierConfig
from task_router.adaptive.schemas import DeterministicRoutingResult, RoutingContext


ROOT = Path(__file__).resolve().parents[1]


def make_settings(tmp_path: Path) -> Settings:
    fixture_root = ROOT / "fixtures" / "orchestrator"
    return Settings(
        task_id_prefix="ENG",
        timezone="UTC",
        sqlite_path=tmp_path / "orchestrator.sqlite3",
        artifacts_root=tmp_path / "obsidian",
        task_folder_template="{task_id} - {project_id} {slug}",
        router_provider="mock",
        projects_path=fixture_root / "config" / "projects.yml",
        workflows_path=fixture_root / "config" / "workflows.yml",
        planner_provider="mock",
        planner_model=None,
        planner_timeout_seconds=900,
        default_executor="mock",
        codex_bin="codex",
        codex_model=None,
        codex_timeout_seconds=1800,
        worktrees_root=tmp_path / "worktrees",
        branch_template="ai/{task_id}-{slug}",
        run_tests_after_execution=True,
        require_plan_approval=True,
        require_diff_approval=True,
        require_commit_approval=True,
    )


def test_adaptive_classifier_saves_pending_rule_and_promotion_removes_classifier_call(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))
    parent = orchestrator.create_task(CreateTaskRequest(message="Fix billing-api login bug")).task_id
    message = f"Нужны правки в {parent[-5:]}: query fails on temp table"

    first = orchestrator.route_adaptive(message, {"debug": True})

    assert first.route_type == "linked_correction"
    assert first.parent_task_id == parent
    assert first.used_classifier is True
    assert first.suggested_rule_ids
    assert orchestrator.list_routing_rules("pending")[0]["id"] == first.suggested_rule_ids[0]

    second = orchestrator.route_adaptive(message, {"debug": True})
    assert second.used_classifier is True
    assert second.source == "cheap_classifier"

    orchestrator.promote_routing_rule(first.suggested_rule_ids[0])
    promoted = orchestrator.route_adaptive(message, {"debug": True})

    assert promoted.used_classifier is False
    assert promoted.source == "learned_rule"
    assert promoted.matched_rules == [first.suggested_rule_ids[0]]


def test_negative_examples_prevent_overbroad_correction_rule(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))
    parent = orchestrator.create_task(CreateTaskRequest(message="Fix billing-api login bug")).task_id
    rule = orchestrator.create_routing_rule(
        {
            "rule_type": "intent_pattern",
            "pattern_type": "contains",
            "pattern": "задачу",
            "target_route_type": "linked_correction",
            "target_workflow_id": "task_correction",
            "target_task_kind": "linked_correction",
            "constraints": ["task_ref_exists"],
            "negative_examples": [f"покажи задачу {parent[-5:]}"],
            "status": "active",
            "source": "human",
            "confidence": 0.95,
        }
    )

    decision = orchestrator.route_adaptive(f"Покажи задачу {parent[-5:]}", {"debug": True})

    assert decision.route_type == "question"
    assert decision.source == "static_rule"
    assert rule["id"] not in decision.matched_rules


def test_post_route_adaptive_returns_debug_diagnostics(tmp_path):
    client = TestClient(create_app(make_settings(tmp_path)))
    parent_response = client.post("/tasks", json={"message": "Fix billing-api login bug"})
    parent_id = parent_response.json()["task_id"]

    response = client.post(
        "/route/adaptive",
        json={
            "message": f"Нужны правки в {parent_id[-5:]}: query fails",
            "context": {"source": "web"},
            "debug": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route_type"] == "linked_correction"
    assert payload["used_classifier"] is True
    assert payload["diagnostics"]["classifier_prompt_chars"] <= 12000


def test_post_tasks_uses_adaptive_linked_correction_and_writes_diagnostics(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))
    parent = orchestrator.create_task(CreateTaskRequest(message="Fix billing-api login bug")).task_id

    response = orchestrator.create_task(CreateTaskRequest(message=f"Нужны правки в {parent[-5:]}: query fails"))
    task = orchestrator.task_store.get_task(response.task_id)

    assert response.workflow_id == "task_correction"
    assert task.parent_task_id == parent
    assert task.correction_source == "adaptive_routing"
    assert orchestrator.task_store.get_artifact(task.id, "routing_diagnostics") is not None
    assert orchestrator.task_store.get_artifact(task.id, "routing_diagnostics_json") is not None
    assert orchestrator.task_store.get_artifact(task.id, "todo", version=1) is None


def test_classifier_prompt_excludes_heavy_context_and_respects_budget():
    config = CheapClassifierConfig(max_prompt_chars=3000)
    deterministic = DeterministicRoutingResult(route_type="unknown", confidence=0.4)
    prompt = build_classifier_prompt(
        "Нужны правки в 00011",
        RoutingContext(source="web"),
        deterministic,
        projects=[{"id": "billing-api", "name": "Billing", "aliases": ["billing"]}],
        recent_tasks=[{"id": f"ENG-2026-{index:05d}", "title": "x" * 200} for index in range(30)],
        active_rules=[{"id": f"rule-{index}", "pattern": "x" * 100, "target_route_type": "linked_correction"} for index in range(30)],
        config=config,
    )

    assert len(prompt) <= 3000
    assert "source_code" in prompt
    assert "runtime_logs" in prompt
    assert "x" * 200 not in prompt
