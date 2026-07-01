export const EMPTY = "нет";
export const UNKNOWN = "неизвестно";

const STATUS_LABELS: Record<string, string> = {
  created: "создана",
  routing: "подбирается маршрут",
  routed: "маршрут выбран",
  awaiting_clarification: "нужно уточнение",
  awaiting_parent_task_clarification: "нужна связанная задача",
  awaiting_tool_health_override: "нужна ручная проверка инструментов",
  planning: "готовится план",
  awaiting_plan_approval: "требуется подтверждение плана",
  awaiting_spec_approval: "требуется подтверждение ТЗ",
  awaiting_config_approval: "требуется подтверждение настроек",
  awaiting_migration_approval: "требуется подтверждение миграции",
  awaiting_security_approval: "требуется подтверждение безопасности",
  plan_rejected: "план отклонен",
  approved_for_execution: "разрешено выполнение",
  preparing_worktree: "готовится рабочая копия",
  executing: "выполняется",
  validating: "проверяется",
  reviewing: "идет ревью",
  validation_failed: "проверка не прошла",
  awaiting_diff_approval: "требуется подтверждение изменений",
  awaiting_diff_reapproval: "нужно повторно подтвердить изменения",
  awaiting_scope_escalation_approval: "требуется подтверждение расширения объема",
  changes_requested: "нужны правки",
  correction_requested: "правки запрошены",
  classifying_correction: "оцениваются правки",
  executing_correction: "правки выполняются",
  validating_correction: "правки проверяются",
  awaiting_correction_diff_approval: "требуется подтверждение правок",
  correction_blocked: "правка заблокирована",
  awaiting_commit_approval: "требуется подтверждение фиксации",
  approved_for_commit: "фиксация разрешена",
  committing: "фиксируются изменения",
  deploy_prep: "готовится выпуск",
  awaiting_deploy_approval: "требуется подтверждение выпуска",
  closed: "закрыта",
  failed: "ошибка",
  prompt_too_large: "контекст слишком большой",
  cancelled: "отменена",
  pending: "ожидает",
  approved: "подтверждено",
  active: "активно",
  rejected: "отклонено",
  edited: "изменено",
  disabled: "отключено",
  succeeded: "успешно",
  running: "в работе",
  queued: "в очереди",
};

const GATE_LABELS: Record<string, string> = {
  clarification: "уточнение",
  tool_health_override: "ручная проверка инструментов",
  scope_escalation: "расширение объема",
  plan: "план",
  spec: "техническое задание",
  config_change: "изменение настроек",
  migration: "миграция",
  security_change: "безопасность",
  diff: "изменения в коде",
  commit: "фиксация изменений",
  deploy_prep: "подготовка выпуска",
  deploy: "выпуск",
};

const RISK_LABELS: Record<string, string> = {
  low: "низкий",
  medium: "средний",
  high: "высокий",
  critical: "критический",
};

const COMPLEXITY_LABELS: Record<string, string> = {
  simple: "простая",
  medium: "средняя",
  complex: "сложная",
};

const ARTIFACT_LABELS: Record<string, string> = {
  task_index: "Сводка задачи",
  route_decision: "Маршрут",
  context_summary: "Контекст",
  working_memory: "Рабочие заметки",
  spec: "Техническое задание",
  todo: "План работ",
  test_plan: "План проверки",
  approval_request: "Запрос подтверждения",
  execution_log: "Журнал выполнения",
  validation_report: "Отчет проверки",
  evaluation_report: "Оценка результата",
  review_report: "Ревью",
  diff_summary: "Сводка изменений",
  diff_patch: "Патч",
  commit_message: "Сообщение фиксации",
  commit_result: "Результат фиксации",
  deploy_plan: "План выпуска",
  rollback_plan: "План отката",
  final_report: "Итоговый отчет",
  events: "События",
};

export function statusLabel(value?: string | null): string {
  if (!value) return UNKNOWN;
  return STATUS_LABELS[value] || humanizeIdentifier(value);
}

export function gateLabel(value?: string | null): string {
  if (!value) return EMPTY;
  return GATE_LABELS[value] || humanizeIdentifier(value);
}

export function riskLabel(value?: string | null): string {
  if (!value) return EMPTY;
  return RISK_LABELS[value] || humanizeIdentifier(value);
}

export function complexityLabel(value?: string | null): string {
  if (!value) return EMPTY;
  return COMPLEXITY_LABELS[value] || humanizeIdentifier(value);
}

export function artifactKindLabel(value?: string | null): string {
  if (!value) return UNKNOWN;
  return ARTIFACT_LABELS[value] || humanizeIdentifier(value);
}

export function displayValue(value?: string | number | boolean | null): string {
  if (value === null || value === undefined || value === "") return EMPTY;
  if (typeof value === "boolean") return value ? "да" : "нет";
  return String(value);
}

export function formatDate(value?: string | null): string {
  return value ? new Date(value).toLocaleString("ru-RU") : EMPTY;
}

export function userFacingError(): string {
  return "Не удалось загрузить данные. Проверьте подключение к серверу и попробуйте еще раз.";
}

export function humanizeIdentifier(value: string): string {
  return value.replace(/[_-]+/g, " ").trim() || UNKNOWN;
}
