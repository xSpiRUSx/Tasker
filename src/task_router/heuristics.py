from __future__ import annotations

from task_router.models import (
    ApprovalGate,
    Complexity,
    RiskLevel,
    RouterConfig,
    TaskIntent,
    TaskKind,
    UserTaskAnalysis,
    WorkflowConfig,
)

COMPLEXITY_ORDER: list[Complexity] = ["trivial", "simple", "medium", "complex", "epic"]


def complexity_score(complexity: Complexity) -> int:
    return COMPLEXITY_ORDER.index(complexity) + 1


def infer_project_id(text: str, config: RouterConfig) -> tuple[str | None, float]:
    lowered = text.lower()
    best_project_id: str | None = None
    best_score = 0

    for project in config.projects.values():
        raw_candidates = [project.id, project.name, project.path, *project.aliases]
        candidates = [item.strip().lower() for item in raw_candidates if item and item.strip()]
        score = sum(1 for item in candidates if item in lowered)
        if score > best_score:
            best_project_id = project.id
            best_score = score

    if best_project_id is None and len(config.projects) == 1:
        return next(iter(config.projects)), 0.5

    if best_project_id is None:
        return None, 0.0
    return best_project_id, min(0.95, 0.55 + best_score * 0.2)


def infer_complexity(text: str) -> Complexity:
    lowered = text.lower()
    if any(word in lowered for word in ["архитект", "миграц", "перепис", "epic", "много проектов"]):
        return "epic"
    if any(word in lowered for word in ["сложно", "рефактор", "безопасн", "интеграц", "производитель"]):
        return "complex"
    if any(word in lowered for word in ["добав", "исправ", "сдел", "реализ", "измен"]):
        return "medium"
    if any(word in lowered for word in ["почему", "как", "где", "найди", "проверь"]):
        return "simple"
    return "trivial"


def infer_intent(text: str) -> TaskIntent:
    lowered = text.lower()
    if any(word in lowered for word in ["напиши", "создай", "сделай", "добав", "исправ", "реализ", "измени", "сгенерируй"]):
        return "code_change"
    if any(word in lowered for word in ["проверь", "найди", "посмотри", "проанализ", "исслед"]):
        return "investigation"
    if any(word in lowered for word in ["как", "что", "почему", "какой", "какая", "какие", "?"]):
        return "question"
    return "unknown"


def infer_task_kind(text: str, intent: TaskIntent) -> TaskKind:
    lowered = text.lower()
    if intent == "question":
        return "question"
    if any(word in lowered for word in ["внешн", "обработк", "отчет", "отчёт", "epf", "erf"]):
        return "external_report_or_processing"
    if any(word in lowered for word in ["миграц", "migration", "alembic", "schema", "схем"]):
        return "migration"
    if any(word in lowered for word in ["deploy", "деплой", "production", "prod", "релиз", "ci", "cd"]):
        return "deployment_change"
    if any(word in lowered for word in ["security", "безопасн", "permission", "role", "роль", "права", "auth", "логин", "парол", "токен"]):
        return "security_change"
    if any(word in lowered for word in ["dependency", "зависим", "package.json", "pyproject", "requirements", "пакет"]):
        return "dependency_change"
    if any(word in lowered for word in ["реквизит", "справочник", "документ", "регистр", "форма", "роль", "подсистем"]):
        return "configuration_change"
    if any(word in lowered for word in ["баг", "bug", "ошиб", "не работает", "исправ"]):
        return "bugfix"
    if any(word in lowered for word in ["фича", "feature", "добавь", "добавить"]):
        return "feature"
    if any(word in lowered for word in ["рефактор", "refactor"]):
        return "refactor"
    if any(word in lowered for word in ["тест", "test", "pytest"]):
        return "test_update"
    if any(word in lowered for word in ["документ", "readme", "docs", "описание"]):
        return "docs_update"
    if any(word in lowered for word in ["код", "запрос", "фрагмент", "процедур", "функци", "текстом", "в ответе"]):
        return "inline_code_or_query"
    if intent == "investigation":
        return "investigation"
    return "unknown"


def infer_risk_flags(text: str, task_kind: TaskKind) -> list[str]:
    lowered = text.lower()
    flags: list[str] = []

    risk_keywords = {
        "auth": ["auth", "login", "логин", "авториза", "парол", "token", "токен"],
        "payments": ["payment", "billing", "оплат", "платеж", "счет", "invoice"],
        "configuration_change": ["config", "env", "конфиг", "настройк", ".env"],
        "migration": ["migration", "миграц", "alembic", "schema", "схем"],
        "security": ["security", "безопасн", "permission", "role", "роль", "права"],
        "deployment": ["deploy", "деплой", "production", "prod", "релиз", "ci", "cd"],
        "dependencies": ["dependency", "зависим", "package.json", "pyproject", "requirements"],
    }

    for flag, keywords in risk_keywords.items():
        if any(keyword in lowered for keyword in keywords):
            flags.append(flag)

    if task_kind == "configuration_change" and "configuration_change" not in flags:
        flags.append("configuration_change")
    if task_kind == "migration" and "migration" not in flags:
        flags.append("migration")
    if task_kind == "deployment_change" and "deployment" not in flags:
        flags.append("deployment")
    if task_kind == "dependency_change" and "dependencies" not in flags:
        flags.append("dependencies")
    if task_kind == "security_change" and "security" not in flags:
        flags.append("security")

    return list(dict.fromkeys(flags))


def infer_risk_level(complexity: Complexity, risk_flags: list[str]) -> RiskLevel:
    high_risk = {"auth", "payments", "security", "migration", "deployment", "configuration_change"}
    if "deployment" in risk_flags and ("migration" in risk_flags or "security" in risk_flags):
        return "critical"
    if high_risk & set(risk_flags):
        return "high"
    if complexity in {"medium", "complex", "epic"}:
        return "medium"
    return "low"


def infer_risk(text: str, complexity: Complexity, task_kind: TaskKind) -> tuple[RiskLevel, list[str]]:
    flags = infer_risk_flags(text, task_kind)
    return infer_risk_level(complexity, flags), flags


def approval_gates_for(
    intent: TaskIntent,
    task_kind: TaskKind,
    risk_level: RiskLevel,
    risk_flags: list[str],
) -> list[str]:
    gates: list[ApprovalGate] = []
    if intent == "question":
        return gates
    if intent == "code_change":
        gates.extend(["plan", "diff"])
    if "configuration_change" in risk_flags or task_kind == "configuration_change":
        gates.append("config_change")
    if "migration" in risk_flags or task_kind == "migration":
        gates.append("migration")
    if "security" in risk_flags or "auth" in risk_flags or task_kind == "security_change":
        gates.append("security_change")
    if "deployment" in risk_flags or task_kind == "deployment_change":
        gates.append("deploy_prep")
    if risk_level in {"high", "critical"}:
        gates.append("spec")
    if risk_level == "critical" and ("deployment" in risk_flags or task_kind == "deployment_change"):
        gates.append("deploy")
    if intent == "code_change":
        gates.append("commit")
    return list(dict.fromkeys(gates))


def requirement_flags(
    intent: TaskIntent,
    task_kind: TaskKind,
    complexity: Complexity,
    risk_level: RiskLevel,
    risk_flags: list[str],
) -> dict[str, bool]:
    requires_code_change = intent == "code_change"
    requires_spec = risk_level in {"high", "critical"} or task_kind in {
        "configuration_change",
        "dependency_change",
        "migration",
        "deployment_change",
        "security_change",
        "architecture_change",
    }
    return {
        "requires_spec": requires_spec,
        "requires_tests": requires_code_change and task_kind not in {"inline_code_or_query", "docs_update"},
        "requires_review": requires_code_change or risk_level in {"high", "critical"},
        "requires_config_approval": "configuration_change" in risk_flags or task_kind == "configuration_change",
        "requires_deploy_prep": "deployment" in risk_flags or task_kind in {"deployment_change", "migration"} or risk_level == "critical",
    }


def choose_workflow(
    analysis: UserTaskAnalysis,
    config: RouterConfig,
) -> tuple[WorkflowConfig | None, list[str]]:
    warnings: list[str] = []
    project_id = analysis.project_id

    if analysis.workflow_id in config.workflows:
        proposed = config.workflows[analysis.workflow_id]
        if (
            proposed.supports_project(project_id)
            and proposed.supports_complexity(analysis.complexity)
            and proposed.supports_intent(analysis.intent)
            and proposed.supports_task_kind(analysis.task_kind)
        ):
            return proposed, warnings
        warnings.append(f"LLM proposed workflow '{analysis.workflow_id}', but it is not eligible.")

    eligible = [
        workflow
        for workflow in config.workflows.values()
        if workflow.supports_project(project_id)
        and workflow.supports_complexity(analysis.complexity)
        and workflow.supports_intent(analysis.intent)
        and workflow.supports_task_kind(analysis.task_kind)
    ]

    if not project_id or analysis.project_confidence < 0.45:
        warnings.append("Project is ambiguous or low-confidence.")
        if "clarify" in config.workflows:
            return config.workflows["clarify"], warnings

    if not eligible:
        warnings.append("No configured workflow matches project, intent, task kind, and complexity.")
        if "clarify" in config.workflows:
            return config.workflows["clarify"], warnings
        return None, warnings

    project_tools = set(config.projects[project_id].tools) if project_id in config.projects else set()
    eligible.sort(
        key=lambda workflow: (
            len(set(workflow.required_tools) & set(analysis.required_tool_ids)),
            len(set(workflow.required_tools) & project_tools),
            -len(workflow.required_tools),
        ),
        reverse=True,
    )
    return eligible[0], warnings


def mock_analyze(text: str, config: RouterConfig) -> UserTaskAnalysis:
    project_id, project_confidence = infer_project_id(text, config)
    complexity = infer_complexity(text)
    intent = infer_intent(text)
    task_kind = infer_task_kind(text, intent)
    risk_level, risk_flags = infer_risk(text, complexity, task_kind)
    approval_gates = approval_gates_for(intent, task_kind, risk_level, risk_flags)
    requirements = requirement_flags(intent, task_kind, complexity, risk_level, risk_flags)

    required_tool_ids = ["codex"]

    return UserTaskAnalysis(
        normalized_task=text.strip(),
        intent=intent,
        task_kind=task_kind,
        project_id=project_id,
        project_confidence=project_confidence,
        complexity=complexity,
        complexity_score=complexity_score(complexity),
        risk_level=risk_level,
        risk_flags=risk_flags,
        approval_gates=approval_gates,
        missing_info=[],
        assumptions=[],
        workflow_id=None,
        workflow_confidence=0.0,
        required_tool_ids=sorted(set(required_tool_ids)),
        rationale="Mock classifier used keyword and alias matching.",
        **requirements,
    )
