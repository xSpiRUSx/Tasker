import { Hammer, RefreshCcw, ShieldCheck, Wrench } from "lucide-react";
import { repairTaskState, runTaskAction } from "../api/client";
import type { Task } from "../api/types";

interface ActionPanelProps {
  busy: string | null;
  onRefresh: () => Promise<void>;
  setError: (message: string | null) => void;
  setToast: (message: string | null) => void;
  task: Task;
}

export function ActionPanel({ busy, onRefresh, setError, setToast, task }: ActionPanelProps) {
  const actions = actionsForStatus(String(task.status));

  async function run(action: string) {
    try {
      const job = await runTaskAction(task.id, action);
      setToast(`${job.action} поставлено в очередь`);
      await onRefresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Действие не выполнено");
    }
  }

  async function repair() {
    try {
      await repairTaskState(task.id);
      setToast("Состояние задачи восстановлено");
      await onRefresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось восстановить состояние");
    }
  }

  return (
    <section className="panel">
      <h2>Действия</h2>
      <div className="button-row">
        {actions.map((action) => (
          <button key={action.id} type="button" disabled={busy !== null} onClick={() => void run(action.id)}>
            {action.icon}
            {action.label}
          </button>
        ))}
        <button type="button" disabled={busy !== null} onClick={() => void repair()}>
          <Wrench size={16} />
          Починить состояние
        </button>
      </div>
    </section>
  );
}

function actionsForStatus(status: string) {
  if (status === "executor_failed" || status === "failed") {
    return [
      { id: "retry-execution", label: "Повторить выполнение", icon: <RefreshCcw size={16} /> },
      { id: "compact-context", label: "Сжать контекст", icon: <Hammer size={16} /> },
    ];
  }
  if (status === "prompt_too_large") {
    return [{ id: "compact-context", label: "Сжать контекст", icon: <Hammer size={16} /> }];
  }
  if (status === "validation_failed") {
    return [
      { id: "retry-validation", label: "Повторить проверку", icon: <RefreshCcw size={16} /> },
      { id: "skip-validation-manual", label: "Ручная проверка", icon: <ShieldCheck size={16} /> },
    ];
  }
  if (status === "changes_requested" || status === "correction_blocked") {
    return [
      { id: "compact-context", label: "Сжать контекст", icon: <Hammer size={16} /> },
      { id: "rebuild-context", label: "Пересобрать контекст", icon: <RefreshCcw size={16} /> },
    ];
  }
  return [{ id: "rebuild-context", label: "Пересобрать контекст", icon: <RefreshCcw size={16} /> }];
}
