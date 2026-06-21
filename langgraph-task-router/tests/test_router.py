from __future__ import annotations

import os
from pathlib import Path

import pytest

from task_router.config_loader import load_router_config
from task_router.graph import build_graph
from task_router.heuristics import infer_intent, infer_project_id, infer_task_kind
from task_router.models import ProjectConfig, RouterConfig, ToolConfig, WorkflowConfig


ROOT = Path(__file__).resolve().parents[1]


def test_mock_routes_any_task_to_solvix_simple_question():
    os.environ["TASK_ROUTER_MOCK_LLM"] = "1"
    config = load_router_config(ROOT / "config" / "projects.yml", ROOT / "config" / "workflows.yml")
    app = build_graph(config)

    state = app.invoke({"input_text": "Какой путь у проекта Solvix_ZN?"})

    assert state["result"].project_id == "solvix_zn"
    assert state["result"].project_name == "Solvix_ZN"
    assert state["result"].project_path == r"C:\Configuration\Solvix_ZN"
    assert state["result"].intent == "question"
    assert state["result"].task_kind == "question"
    assert state["result"].workflow_id == "simple_question"
    assert state["result"].workflow_name == "Простой вопрос"
    assert state["result"].recommended_tool_ids == ["codex"]
    assert state["result"].requires_spec is False
    assert state["result"].approval_gates == []


def test_config_has_two_projects_and_two_workflows():
    config = load_router_config(ROOT / "config" / "projects.yml", ROOT / "config" / "workflows.yml")

    assert list(config.projects) == ["solvix_zn", "sq_erp_ext"]
    assert list(config.workflows) == ["simple_question", "simple_external_development"]
    assert config.projects["sq_erp_ext"].tools == ["codex", "1c-graph-metadata-mcp"]


def test_mock_routes_sq_project_with_metadata_mcp_tool():
    os.environ["TASK_ROUTER_MOCK_LLM"] = "1"
    config = load_router_config(ROOT / "config" / "projects.yml", ROOT / "config" / "workflows.yml")
    app = build_graph(config)

    state = app.invoke({"input_text": "Снежная королева ЕРП: что хранится в справочнике Номенклатура?"})

    assert state["result"].project_id == "sq_erp_ext"
    assert state["result"].project_name == "Снежная королева ЕРП"
    assert state["result"].project_path == r"C:\Configuration\SQ_ERP\ERP_Ext"
    assert state["result"].workflow_id == "simple_question"
    assert state["result"].recommended_tool_ids == ["1c-graph-metadata-mcp", "codex"]


def test_mock_routes_simple_processing_to_external_development():
    os.environ["TASK_ROUTER_MOCK_LLM"] = "1"
    config = load_router_config(ROOT / "config" / "projects.yml", ROOT / "config" / "workflows.yml")
    app = build_graph(config)

    state = app.invoke({"input_text": "Solvix_ZN: напиши простую обработку которая напишет привет мир"})

    assert state["result"].project_id == "solvix_zn"
    assert state["result"].intent == "code_change"
    assert state["result"].task_kind == "external_report_or_processing"
    assert state["result"].workflow_id == "simple_external_development"
    assert state["result"].workflow_name == "Простая разработка без доработки конфигурации"
    assert state["result"].recommended_tool_ids == ["codex"]
    assert state["result"].requires_review is True
    assert state["result"].approval_gates == ["plan", "diff", "commit"]


def test_mock_returns_no_workflow_for_configuration_change():
    os.environ["TASK_ROUTER_MOCK_LLM"] = "1"
    config = load_router_config(ROOT / "config" / "projects.yml", ROOT / "config" / "workflows.yml")
    app = build_graph(config)

    state = app.invoke({"input_text": "Solvix_ZN: добавь реквизит Комментарий в справочник Номенклатура"})

    assert state["result"].project_id == "solvix_zn"
    assert state["result"].intent == "code_change"
    assert state["result"].task_kind == "configuration_change"
    assert state["result"].workflow_id is None
    assert state["result"].workflow_name is None
    assert state["result"].warnings == ["No configured workflow matches project, intent, task kind, and complexity."]
    assert state["result"].requires_config_approval is True


def test_project_inference_does_not_match_empty_path():
    config = RouterConfig(
        tools={"codex": ToolConfig(id="codex", name="Codex", type="llm", description="LLM")},
        projects={
            "first": ProjectConfig(id="first", name="First", path=None, aliases=[], description="First", tools=["codex"]),
            "second": ProjectConfig(id="second", name="Second", path=None, aliases=["target"], description="Second", tools=["codex"]),
        },
        workflows={},
    )

    project_id, confidence = infer_project_id("plain text without project marker", config)

    assert project_id is None
    assert confidence == 0.0


def test_unknown_is_not_workflow_wildcard():
    workflow = WorkflowConfig(
        id="unknown_only",
        name="Unknown only",
        description="Only unknown intent",
        project_ids=["*"],
        intents=["unknown"],
        task_kinds=["unknown"],
        complexity=["simple"],
    )

    assert workflow.supports_intent("unknown") is True
    assert workflow.supports_intent("question") is False
    assert workflow.supports_task_kind("unknown") is True
    assert workflow.supports_task_kind("inline_code_or_query") is False


def test_star_is_workflow_wildcard():
    workflow = WorkflowConfig(
        id="wildcard",
        name="Wildcard",
        description="Wildcard",
        project_ids=["*"],
        intents=["*"],
        task_kinds=["*"],
        complexity=["simple"],
    )

    assert workflow.supports_intent("question") is True
    assert workflow.supports_task_kind("configuration_change") is True


def test_external_report_with_catalog_word_is_not_config_change():
    text = "Сделай внешний отчет по справочнику Контрагенты"
    intent = infer_intent(text)

    assert intent == "code_change"
    assert infer_task_kind(text, intent) == "external_report_or_processing"


def test_auth_config_change_requires_security_or_config_gates():
    os.environ["TASK_ROUTER_MOCK_LLM"] = "1"
    config = load_router_config(ROOT / "config" / "projects.yml", ROOT / "config" / "workflows.yml")
    app = build_graph(config)

    state = app.invoke({"input_text": "Solvix_ZN: исправь логин после изменения env-конфига"})

    assert state["result"].risk_level == "high"
    assert "auth" in state["result"].risk_flags
    assert "configuration_change" in state["result"].risk_flags
    assert "security_change" in state["result"].approval_gates
    assert "config_change" in state["result"].approval_gates
    assert state["result"].requires_spec is True
    assert state["result"].requires_review is True
    assert state["result"].requires_config_approval is True


def test_invalid_workflow_without_complexity_is_rejected(tmp_path):
    projects_path = tmp_path / "projects.yml"
    workflows_path = tmp_path / "workflows.yml"

    projects_path.write_text(
        """
tools:
  - id: codex
    name: Codex
    type: llm
    description: LLM
projects:
  - id: demo
    name: Demo
    description: Demo project
    tools: ["codex"]
""".strip(),
        encoding="utf-8",
    )
    workflows_path.write_text(
        """
workflows:
  - id: broken
    name: Broken
    description: Missing complexity
    project_ids: ["demo"]
    complexity: []
    required_tools: ["codex"]
    steps:
      - answer
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must define at least one complexity"):
        load_router_config(projects_path, workflows_path)
