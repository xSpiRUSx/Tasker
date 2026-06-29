export const EMPTY = "нет";
export const UNKNOWN = "неизвестно";

const STATUS_LABELS: Record<string, string> = {
  created: "создана",
  routing: "маршрутизация",
  routed: "маршрут выбран",
  awaiting_clarification: "нужно уточнение",
  planning: "планирование",
  awaiting_plan_approval: "ожидает план",
  awaiting_spec_approval: "ожидает ТЗ",
  awaiting_config_approval: "ожидает конфиг",
  awaiting_migration_approval: "ожидает миграцию",
  awaiting_security_approval: "ожидает безопасность",
  plan_rejected: "план отклонен",
  approved_for_execution: "разрешено выполнение",
  preparing_worktree: "подготовка worktree",
  executing: "выполнение",
  validating: "проверка",
  reviewing: "ревью",
  validation_failed: "проверка не прошла",
  awaiting_diff_approval: "ожидает diff",
  awaiting_diff_reapproval: "повторное diff-ревью",
  changes_requested: "нужны правки",
  correction_requested: "запрошена правка",
  classifying_correction: "классификация правки",
  executing_correction: "правка выполняется",
  validating_correction: "проверка правки",
  awaiting_correction_diff_approval: "ожидает diff правки",
  correction_blocked: "правка заблокирована",
  awaiting_commit_approval: "ожидает коммит",
  approved_for_commit: "коммит разрешен",
  committing: "коммит",
  deploy_prep: "подготовка релиза",
  awaiting_deploy_approval: "ожидает релиз",
  closed: "закрыта",
  failed: "ошибка",
  prompt_too_large: "контекст велик",
  cancelled: "отменена",
  pending: "ожидает",
  active: "активно",
  rejected: "отклонено",
  disabled: "отключено",
  succeeded: "успешно",
  running: "в работе",
  queued: "в очереди",
};

const GATE_LABELS: Record<string, string> = {
  clarification: "уточнение",
  plan: "план",
  spec: "ТЗ",
  config_change: "изменение конфигурации",
  migration: "миграция",
  security_change: "безопасность",
  diff: "diff",
  commit: "коммит",
  deploy_prep: "подготовка релиза",
  deploy: "релиз",
};

export function statusLabel(value?: string | null): string {
  if (!value) return UNKNOWN;
  return STATUS_LABELS[value] || value;
}

export function gateLabel(value?: string | null): string {
  if (!value) return EMPTY;
  return GATE_LABELS[value] || value;
}

export function displayValue(value?: string | number | boolean | null): string {
  if (value === null || value === undefined || value === "") return EMPTY;
  return String(value);
}

export function formatDate(value?: string | null): string {
  return value ? new Date(value).toLocaleString("ru-RU") : EMPTY;
}
