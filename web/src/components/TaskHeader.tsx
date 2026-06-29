import { Ban, RefreshCw } from "lucide-react";
import type { Task } from "../api/types";
import { displayValue, formatDate } from "../i18n";
import { StatusBadge } from "./StatusBadge";

interface TaskHeaderProps {
  busy: string | null;
  onCancel: (comment: string) => Promise<void>;
  task: Task;
}

export function TaskHeader({ busy, onCancel, task }: TaskHeaderProps) {
  async function cancel() {
    const comment = window.prompt(`Отменить ${task.id}?`, "Отменено пользователем");
    if (comment === null) return;
    if (!window.confirm(`Задача ${task.id} будет отменена вместе с ожидающими approvals.`)) return;
    await onCancel(comment);
  }

  return (
    <section className="task-header">
      <div>
        <div className="task-header__title">
          <h1>{task.id}</h1>
          <StatusBadge status={task.status} />
        </div>
        <dl className="task-header__meta">
          <Meta label="router" value={task.runtime?.router} />
          <Meta label="planner" value={task.runtime?.planner} />
          <Meta label="executor" value={task.runtime?.executor} />
          <Meta label="mode" value={task.runtime?.mode} />
          <Meta label="project" value={task.project_id} />
          <Meta label="workflow" value={task.workflow_id} />
          <Meta label="risk" value={task.risk_level} />
          <Meta label="job" value={task.latest_job ? `${task.latest_job.action} / ${task.latest_job.status}` : null} />
          <Meta label="branch" value={task.branch_name} />
          <Meta label="worktree" value={task.worktree_path} />
          <Meta label="artifacts" value={task.artifacts_dir} />
          <Meta label="created" value={formatDate(task.created_at)} />
          <Meta label="updated" value={formatDate(task.updated_at)} />
          <Meta label="closed" value={formatDate(task.closed_at)} />
        </dl>
        {task.runtime?.mode === "dry-run" ? (
          <p className="task-header__warning">План или выполнение используют mock-режим. Перед live-выполнением пересоберите задачу с реальными провайдерами.</p>
        ) : null}
        {task.status === "prompt_too_large" ? (
          <p className="task-header__warning">Контекст исполнителя превысил бюджет. Перед повтором нужно сжать контекст.</p>
        ) : null}
      </div>
      <div className="task-header__actions">
        <button type="button" onClick={() => window.location.reload()} title="Обновить приложение">
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
