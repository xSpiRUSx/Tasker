from __future__ import annotations

import os
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from task_router.codex_cli import analyze_with_codex_cli
from task_router.heuristics import choose_workflow, complexity_score, mock_analyze
from task_router.llm import analyze_with_llm
from task_router.models import RouteDecision, RouterConfig, UserTaskAnalysis, WorkflowConfig


class RouterState(TypedDict, total=False):
    input_text: str
    analysis: UserTaskAnalysis
    selected_workflow: WorkflowConfig | None
    warnings: list[str]
    result: RouteDecision


def build_graph(config: RouterConfig, structured_llm: Any | None = None, provider: str | None = None):
    graph = StateGraph(RouterState)

    def workflow_node_name(workflow_id: str) -> str:
        return f"workflow__{workflow_id}"

    def merge_unique(*items: list[str]) -> list[str]:
        values: list[str] = []
        for group in items:
            values.extend(group)
        return list(dict.fromkeys(values))

    def apply_deterministic_overrides(analysis: UserTaskAnalysis) -> None:
        def add_flag(flag: str) -> None:
            if flag not in analysis.risk_flags:
                analysis.risk_flags.append(flag)

        def add_gate(gate: str) -> None:
            if gate not in analysis.approval_gates:
                analysis.approval_gates.append(gate)

        if analysis.task_kind == "configuration_change":
            analysis.requires_config_approval = True
            analysis.requires_spec = True
            analysis.requires_review = True
            add_flag("configuration_change")
            add_gate("config_change")
        elif analysis.task_kind == "migration":
            analysis.requires_spec = True
            analysis.requires_tests = True
            analysis.requires_review = True
            add_flag("migration")
            add_gate("migration")
        elif analysis.task_kind == "security_change":
            analysis.requires_spec = True
            analysis.requires_tests = True
            analysis.requires_review = True
            add_flag("security")
            add_gate("security_change")
        elif analysis.task_kind == "deployment_change":
            analysis.requires_deploy_prep = True
            add_flag("deployment")
            add_gate("deploy_prep")

        if "configuration_change" in analysis.risk_flags:
            analysis.requires_config_approval = True
            add_gate("config_change")
        if "migration" in analysis.risk_flags:
            analysis.requires_spec = True
            analysis.requires_tests = True
            analysis.requires_review = True
            add_gate("migration")
        if "security" in analysis.risk_flags or "auth" in analysis.risk_flags:
            analysis.requires_spec = True
            analysis.requires_tests = True
            analysis.requires_review = True
            add_gate("security_change")
        if "deployment" in analysis.risk_flags:
            analysis.requires_deploy_prep = True
            add_gate("deploy_prep")

        if analysis.risk_level == "low" and set(analysis.risk_flags) & {
            "auth",
            "payments",
            "security",
            "migration",
            "deployment",
            "configuration_change",
        }:
            analysis.risk_level = "high"

        if analysis.intent == "code_change":
            add_gate("plan")
            add_gate("diff")
            add_gate("commit")

    def classify(state: RouterState) -> RouterState:
        selected_provider = provider or os.getenv("TASK_ROUTER_PROVIDER", "codex-cli")
        if os.getenv("TASK_ROUTER_MOCK_LLM") == "1" or selected_provider == "mock":
            analysis = mock_analyze(state["input_text"], config)
        elif selected_provider == "codex-cli":
            analysis = analyze_with_codex_cli(state["input_text"], config)
        elif selected_provider == "openai-api":
            analysis = analyze_with_llm(state["input_text"], config, structured_llm)
        else:
            raise ValueError(f"Unknown task router provider: {selected_provider}")
        return {"analysis": analysis}

    def validate_route(state: RouterState) -> RouterState:
        analysis = state["analysis"]
        warnings: list[str] = []

        if analysis.project_id not in config.projects:
            if len(config.projects) == 1:
                project = next(iter(config.projects.values()))
                warnings.append(f"Project '{analysis.project_id}' is not configured; using the only configured project.")
                analysis.project_id = project.id
                analysis.project_confidence = max(analysis.project_confidence, 0.5)
            else:
                warnings.append(f"Project '{analysis.project_id}' is not configured.")
                analysis.project_id = None
                analysis.project_confidence = 0.0

        known_tools = set(config.tools)
        unknown_tools = sorted(set(analysis.required_tool_ids) - known_tools)
        if unknown_tools:
            warnings.append("Unknown tools removed: " + ", ".join(unknown_tools))
            analysis.required_tool_ids = [tool_id for tool_id in analysis.required_tool_ids if tool_id in known_tools]

        expected_complexity_score = complexity_score(analysis.complexity)
        if analysis.complexity_score != expected_complexity_score:
            warnings.append(
                f"Complexity score normalized from {analysis.complexity_score} to {expected_complexity_score}."
            )
            analysis.complexity_score = expected_complexity_score

        apply_deterministic_overrides(analysis)

        workflow, workflow_warnings = choose_workflow(analysis, config)
        warnings.extend(workflow_warnings)
        return {"analysis": analysis, "selected_workflow": workflow, "warnings": warnings}

    def route_to_workflow(state: RouterState) -> str:
        workflow = state.get("selected_workflow")
        if workflow is None:
            return "no_workflow"
        return workflow_node_name(workflow.id)

    def no_workflow(state: RouterState) -> RouterState:
        analysis = state["analysis"]
        project = config.projects.get(analysis.project_id) if analysis.project_id else None
        warnings = state.get("warnings", [])
        project_tool_ids = project.tools if project else []

        result = RouteDecision(
            input_text=state["input_text"],
            normalized_task=analysis.normalized_task,
            project_id=project.id if project else None,
            project_name=project.name if project else None,
            project_path=project.path if project else None,
            project_confidence=analysis.project_confidence,
            complexity=analysis.complexity,
            complexity_score=analysis.complexity_score,
            intent=analysis.intent,
            task_kind=analysis.task_kind,
            risk_level=analysis.risk_level,
            risk_flags=sorted(set(analysis.risk_flags)),
            workflow_id=None,
            workflow_name=None,
            workflow_confidence=analysis.workflow_confidence,
            requires_spec=analysis.requires_spec,
            requires_tests=analysis.requires_tests,
            requires_review=analysis.requires_review,
            requires_config_approval=analysis.requires_config_approval,
            requires_deploy_prep=analysis.requires_deploy_prep,
            approval_gates=analysis.approval_gates,
            recommended_tool_ids=sorted(set(project_tool_ids) | set(analysis.required_tool_ids)),
            confidence=analysis.project_confidence,
            rationale=analysis.rationale,
            missing_info=analysis.missing_info,
            assumptions=analysis.assumptions,
            next_steps=[],
            warnings=warnings,
        )
        return {"result": result}

    def make_workflow_node(workflow: WorkflowConfig):
        def run_workflow(state: RouterState) -> RouterState:
            analysis = state["analysis"]
            project = config.projects.get(analysis.project_id) if analysis.project_id else None
            confidence = min(analysis.project_confidence, max(analysis.workflow_confidence, 0.5))
            project_tool_ids = project.tools if project else []
            tool_ids = sorted(set(project_tool_ids) | set(workflow.required_tools) | set(analysis.required_tool_ids))

            result = RouteDecision(
                input_text=state["input_text"],
                normalized_task=analysis.normalized_task,
                project_id=project.id if project else None,
                project_name=project.name if project else None,
                project_path=project.path if project else None,
                project_confidence=analysis.project_confidence,
                complexity=analysis.complexity,
                complexity_score=analysis.complexity_score,
                intent=analysis.intent,
                task_kind=analysis.task_kind,
                risk_level=analysis.risk_level,
                risk_flags=sorted(set(analysis.risk_flags) | set(workflow.risk_flags)),
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                workflow_confidence=analysis.workflow_confidence,
                requires_spec=analysis.requires_spec or workflow.requires_spec,
                requires_tests=analysis.requires_tests or workflow.requires_tests,
                requires_review=analysis.requires_review or workflow.requires_review,
                requires_config_approval=analysis.requires_config_approval or workflow.requires_config_approval,
                requires_deploy_prep=analysis.requires_deploy_prep or workflow.requires_deploy_prep,
                approval_gates=merge_unique(analysis.approval_gates, workflow.approval_gates),
                recommended_tool_ids=tool_ids,
                confidence=confidence,
                rationale=analysis.rationale,
                missing_info=analysis.missing_info,
                assumptions=analysis.assumptions,
                next_steps=workflow.steps,
                warnings=state.get("warnings", []),
            )
            return {"result": result}

        return run_workflow

    graph.add_node("classify", classify)
    graph.add_node("validate_route", validate_route)
    graph.add_node("no_workflow", no_workflow)
    graph.add_edge("no_workflow", END)

    workflow_mapping: dict[str, str] = {"no_workflow": "no_workflow"}
    for workflow in config.workflows.values():
        node_name = workflow_node_name(workflow.id)
        graph.add_node(node_name, make_workflow_node(workflow))
        graph.add_edge(node_name, END)
        workflow_mapping[node_name] = node_name

    graph.add_edge(START, "classify")
    graph.add_edge("classify", "validate_route")
    graph.add_conditional_edges("validate_route", route_to_workflow, workflow_mapping)

    return graph.compile()
