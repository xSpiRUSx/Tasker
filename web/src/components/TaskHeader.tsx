import { Ban, Copy, RefreshCw } from "lucide-react";
import type { Task } from "../api/types";
import { displayValue, formatDate, riskLabel } from "../i18n";
import { StatusBadge } from "./StatusBadge";

interface TaskHeaderProps {
  advancedUi: boolean;
  busy: string | null;
  onCancel: (comment: string) => Promise<void>;
  task: Task;
}

export function TaskHeader({ advancedUi, busy, onCancel, task }: TaskHeaderProps) {
  async function cancel() {
    const comment = window.prompt("Отменить задачу?", "Отменено пользователем");
    if (comment === null) return;
    if (!window.confirm("Задача будет отменена вместе с ожидающими подтверждениями.")) return;
    await onCancel(comment);
  }

  return (
    <section className="task-header">
      <div>
        <div className="task-header__title">
          <h1>{task.user_message || "Задача"}</h1>
          <StatusBadge status={task.status} />
        </div>
        <dl className="task-header__meta">
          <Meta label="Создано" value={formatDate(task.created_at)} />
          <Meta label="Обновлено" value={formatDate(task.updated_at)} />
          <Meta label="Риск" value={riskLabel(task.risk_level)} />
          {task.closed_at ? <Meta label="Закрыто" value={formatDate(task.closed_at)} /> : null}
          {advancedUi ? (
            <>
              <Meta label="ID" value={task.id} />
              <Meta label="Router" value={task.runtime?.router} />
              <Meta label="Planner" value={task.runtime?.planner} />
              <Meta label="Executor" value={task.runtime?.executor} />
              <Meta label="Mode" value={task.runtime?.mode} />
              <Meta label="project_id" value={task.project_id} />
              <Meta label="workflow_id" value={task.workflow_id} />
              <Meta label="Последняя операция" value={task.latest_job ? `${task.latest_job.action} / ${task.latest_job.status}` : null} />
              <Meta label="Ветка" value={task.branch_name} />
              <Meta label="Рабочая копия" value={task.worktree_path} />
              <Meta label="Папка артефактов" value={task.artifacts_dir} />
            </>
          ) : null}
        </dl>
        {task.runtime?.mode === "dry-run" && advancedUi ? (
          <p className="task-header__warning">
            Задача использует mock-режим. Перед live-выполнением пересоберите ее с реальными провайдерами.
          </p>
        ) : null}
        {task.status === "prompt_too_large" ? (
          <p className="task-header__warning">Контекст исполнителя превысил бюджет. Перед повтором нужно сжать контекст.</p>
        ) : null}
      </div>
      <div className="task-header__actions">
        {advancedUi ? (
          <button type="button" onClick={() => void navigator.clipboard.writeText(task.id)} title="Скопировать ID" aria-label="Скопировать ID задачи">
            <Copy size={16} />
          </button>
        ) : null}
        <button type="button" onClick={() => window.location.reload()} title="Обновить приложение" aria-label="Обновить приложение">
          <RefreshCw size={16} />
        </button>
        <button type="button" disabled={busy === "cancel" || task.status === "closed" || task.status === "cancelled"} onClick={() => void cancel()}>
          <Ban size={16} />
          {busy === "cancel" ? "Отменяю..." : "Отменить"}
        </button>
      </div>
    </section>
  );
}

function Meta({ label, value }: { label: string; value?: string | null }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{displayValue(value)}</dd>
    </>
  );
}
