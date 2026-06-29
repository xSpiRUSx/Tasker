from __future__ import annotations

import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from engineering_orchestrator.llm import LLMGateway
from engineering_orchestrator.llm.types import ModelDecision
from task_router.models import RouterConfig, UserTaskAnalysis


def create_structured_llm():
    model = os.getenv("TASK_ROUTER_MODEL") or os.getenv("TASKER_GPT55_MODEL")
    if not model:
        raise RuntimeError("Set TASK_ROUTER_MODEL or TASKER_GPT55_MODEL before using the LLM router.")
    return ChatOpenAI(model=model).with_structured_output(UserTaskAnalysis, method="json_schema")


def build_router_prompt(config: RouterConfig) -> str:
    projects = "\n".join(
        f"- {project.id}: {project.name}; path={project.path}; aliases={project.aliases}; "
        f"tools={project.tools}; {project.description}"
        for project in config.projects.values()
    )
    workflows = "\n".join(
        f"- {workflow.id}: {workflow.name}; projects={workflow.project_ids}; "
        f"intents={workflow.intents}; task_kinds={workflow.task_kinds}; "
        f"complexity={workflow.complexity}; requires_spec={workflow.requires_spec}; "
        f"requires_tests={workflow.requires_tests}; requires_review={workflow.requires_review}; "
        f"requires_config_approval={workflow.requires_config_approval}; "
        f"requires_deploy_prep={workflow.requires_deploy_prep}; "
        f"use_worktree={workflow.use_worktree}; "
        f"approval_gates={workflow.approval_gates}; risk_flags={workflow.risk_flags}; "
        f"allowed_change_types={workflow.allowed_change_types}; "
        f"blocked_change_types={workflow.blocked_change_types}; "
        f"tools={workflow.required_tools}; {workflow.description}"
        for workflow in config.workflows.values()
    )
    tools = "\n".join(
        f"- {tool.id}: {tool.name} ({tool.type}); {tool.description}" for tool in config.tools.values()
    )

    return f"""
You are a deterministic task-routing classifier.

Your job:
1. Understand the user's free-text task.
2. Pick the best configured project, or null if genuinely ambiguous.
3. Estimate complexity.
4. Classify intent as:
   - question: user asks for an answer or explanation without changes.
   - investigation: user asks to inspect/check/find/analyze before deciding changes.
   - code_change: user asks to create, edit, implement, fix, generate, or modify something.
   - unknown: intent is unclear.
5. Classify task_kind as:
   - question: answer/explanation only, no code artifact requested.
   - bugfix: fix an existing defect without changing architecture.
   - feature: add user-visible behavior without configuration metadata changes.
   - refactor: improve internal structure without behavior changes.
   - test_update: add or change tests.
   - docs_update: add or change documentation.
   - external_report_or_processing: create a 1C external report or external processing, without changing the configuration.
   - inline_code_or_query: write a code snippet or query directly in the answer, without changing files/configuration.
   - configuration_change: change the 1C configuration, metadata, forms, registers, catalogs, documents, roles, or built-in objects.
   - dependency_change: add, remove, or upgrade dependencies.
   - migration: data/schema migration.
   - deployment_change: release, deploy, infra, CI/CD, or runtime environment change.
   - security_change: authentication, authorization, permissions, secrets, tokens, or security-sensitive behavior.
   - architecture_change: broad structure, boundaries, platform, or cross-component design change.
   - investigation: inspect/analyze/check without immediately changing code.
   - unknown: task kind is unclear.
6. Estimate risk_level, risk_flags, approval_gates, and requires_* flags.
7. Pick the best configured workflow, or null if a workflow cannot be chosen safely.
8. Return only the structured schema requested by the caller.

Complexity rubric:
- trivial: tiny factual answer or no project work.
- simple: lookup, explanation, small verification, or one obvious step.
- medium: scoped implementation or investigation across a few files/tools.
- complex: cross-component change, risky behavior, migration, performance, security, or unclear blast radius.
- epic: multi-phase effort that should be split before execution.

Configured tools:
{tools}

Configured projects:
{projects}

Configured workflows:
{workflows}

Rules:
- project_id must be one of the configured project ids, or null.
- workflow_id must be one of the configured workflow ids, or null.
- Do not select a workflow whose intents do not include the classified intent.
- Do not select a workflow whose task_kinds do not include the classified task_kind.
- "*" in workflow intents/task_kinds means wildcard. "unknown" means unknown only, not wildcard.
- If the task requires configuration_change and no such workflow is configured, set workflow_id to null.
- If the task requires code_change and only question workflows are configured, set workflow_id to null.
- Use risk_level=high for security/access, auth, permissions, deploy, production, or data-loss risk.
- Add risk_flags for concrete risks such as security_or_access, configuration_change, dependency_change, migration, deployment, destructive_change.
- Set requires_config_approval=true for configuration_change.
- Set requires_deploy_prep=true for deployment_change or migration.
- Put missing clarifications in missing_info; put assumptions in assumptions.
- required_tool_ids should list likely tools from the configured tools.
- rationale must be short and user-visible; do not include hidden chain-of-thought.
""".strip()


def analyze_with_llm(text: str, config: RouterConfig, structured_llm=None) -> UserTaskAnalysis:
    messages = [SystemMessage(content=build_router_prompt(config)), HumanMessage(content=text)]
    if structured_llm is not None:
        response = structured_llm.invoke(messages)
        if isinstance(response, UserTaskAnalysis):
            return response
        return UserTaskAnalysis.model_validate(response)

    model = os.getenv("TASK_ROUTER_MODEL") or os.getenv("TASKER_GPT55_MODEL")
    if not model:
        raise RuntimeError("Set TASK_ROUTER_MODEL or TASKER_GPT55_MODEL before using the LLM router.")
    decision = ModelDecision(
        target_id="gpt55_medium",
        runtime="responses_api",
        model=model,
        reasoning_effort="medium",
        profile="router",
        operation="route_task",
        reason="task router LLM fallback",
        max_prompt_chars=20000,
        allow_escalation=False,
    )

    def provider(_prompt: str, _decision: ModelDecision) -> str:
        value = create_structured_llm().invoke(messages)
        if isinstance(value, UserTaskAnalysis):
            return value.model_dump_json()
        return UserTaskAnalysis.model_validate(value).model_dump_json()

    result = LLMGateway().call(decision, f"{messages[0].content}\n\n{messages[1].content}", provider=provider)
    response = UserTaskAnalysis.model_validate_json(result.text)
    if isinstance(response, UserTaskAnalysis):
        return response
    return UserTaskAnalysis.model_validate(response)
