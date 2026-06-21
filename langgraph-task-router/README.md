# LangGraph Task Router

Минимальный настраиваемый роутер задач:

```text
свободный текст пользователя
  -> LLM-классификация
  -> проект
  -> intent / task_kind / сложность / риск
  -> workflow
  -> approval gates / список инструментов / следующий план
```

## Что где настраивается

- `config/projects.yml` - проекты, алиасы проектов и доступные инструменты.
- `config/workflows.yml` - workflow, допустимые проекты, уровни сложности, нужные инструменты и шаги.
- `.env` - провайдер LLM и опциональные настройки Codex CLI.

Текущая конфигурация:

- проект: `solvix_zn`, путь `C:\Configuration\Solvix_ZN`;
- проект: `sq_erp_ext`, название `Снежная королева ЕРП`, путь `C:\Configuration\SQ_ERP\ERP_Ext`;
- workflow: `simple_question`, название `Простой вопрос`;
- workflow: `simple_external_development`, название `Простая разработка без доработки конфигурации`;
- инструмент: `codex`.
- инструмент: `1c-graph-metadata-mcp` для проекта `sq_erp_ext`.

## Как запустить

```powershell
cd C:\Users\s314r\Documents\Codex\2026-06-21\vy\outputs\langgraph-task-router
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
Copy-Item .env.example .env
```

Один раз авторизуйтесь в локальном Codex:

```powershell
codex login
```

После этого роутер по умолчанию использует вашу локальную Codex-сессию:

```powershell
task-router "Какой проект сейчас настроен?"
```

Для локальной проверки без вызова LLM:

```powershell
task-router --mock "Какой проект сейчас настроен?"
```

## Авторизация Codex

Основной режим:

```env
TASK_ROUTER_PROVIDER=codex-cli
TASK_ROUTER_CONFIG_DIR=
TASK_ROUTER_CODEX_BIN=codex
TASK_ROUTER_CODEX_MODEL=
```

В этом режиме Python-приложение не хранит `OPENAI_API_KEY`. Узел классификации вызывает:

```powershell
codex exec "..." --output-schema schema.json --skip-git-repo-check
```

Codex CLI сам использует авторизацию, полученную через `codex login`.

Если нужно явно задать модель для `codex exec`, заполните `TASK_ROUTER_CODEX_MODEL`. Если оставить пустым, будет использована модель из настроек Codex.

Запасной режим прямого OpenAI API тоже оставлен:

```env
TASK_ROUTER_PROVIDER=openai-api
OPENAI_API_KEY=...
TASK_ROUTER_MODEL=gpt-5.5
```

## Как это устроено

Граф собирается в `src/task_router/graph.py`:

1. `classify` вызывает LLM со структурированным Pydantic-выводом.
2. `validate_route` проверяет, что проект, workflow и инструменты есть в YAML.
3. `add_conditional_edges` отправляет состояние в узел выбранного workflow.
4. Workflow-узел возвращает `RouteDecision`.

В режиме `codex-cli` узел `classify` запускает локальный `codex exec` с JSON Schema, построенной из модели `UserTaskAnalysis`. LLM получает полный список проектов, инструментов и workflow из конфигов. Поэтому для добавления нового проекта или процесса обычно достаточно изменить YAML.

Если задача не подходит ни под один workflow, роутер возвращает `workflow_id: null`, пустой `next_steps` и предупреждение в `warnings`.

`RouteDecision` также содержит контракт для будущего orchestrator: `risk_level`, `risk_flags`, `approval_gates`, `requires_spec`, `requires_tests`, `requires_review`, `requires_config_approval`, `requires_deploy_prep`, `missing_info` и `assumptions`.

## Пример результата

```json
{
  "project_id": "solvix_zn",
  "project_name": "Solvix_ZN",
  "project_path": "C:\\Configuration\\Solvix_ZN",
  "complexity": "simple",
  "intent": "question",
  "task_kind": "question",
  "risk_level": "low",
  "workflow_id": "simple_question",
  "workflow_name": "Простой вопрос",
  "requires_spec": false,
  "requires_tests": false,
  "requires_review": false,
  "approval_gates": [],
  "recommended_tool_ids": ["codex"],
  "next_steps": [
    "Понять вопрос пользователя.",
    "При необходимости посмотреть контекст проекта C:\\Configuration\\Solvix_ZN.",
    "Дать короткий ответ и явно указать, если данных недостаточно."
  ]
}
```

Пример для проекта `Снежная королева ЕРП`:

```json
{
  "project_id": "sq_erp_ext",
  "project_name": "Снежная королева ЕРП",
  "project_path": "C:\\Configuration\\SQ_ERP\\ERP_Ext",
  "workflow_id": "simple_question",
  "workflow_name": "Простой вопрос",
  "recommended_tool_ids": ["1c-graph-metadata-mcp", "codex"]
}
```

Пример для простой разработки без доработки конфигурации:

```json
{
  "project_id": "solvix_zn",
  "intent": "code_change",
  "task_kind": "external_report_or_processing",
  "risk_level": "low",
  "workflow_id": "simple_external_development",
  "workflow_name": "Простая разработка без доработки конфигурации",
  "requires_review": true,
  "approval_gates": ["plan", "diff", "commit"],
  "recommended_tool_ids": ["codex"]
}
```

Пример для задачи без настроенного workflow:

```json
{
  "project_id": "solvix_zn",
  "intent": "code_change",
  "task_kind": "configuration_change",
  "risk_level": "medium",
  "requires_config_approval": true,
  "workflow_id": null,
  "workflow_name": null,
  "next_steps": [],
  "warnings": [
    "No configured workflow matches project, intent, task kind, and complexity."
  ]
}
```

## Полезные расширения

- Добавить отдельный `confidence_policy.yml`: когда автоматически запускать workflow, а когда задавать вопросы.
- Подключить реальные executors для workflow, когда появятся новые типы задач.
- Логировать вход, решение и итоговый workflow в БД для последующей донастройки классификации.
