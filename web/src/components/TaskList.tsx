import type { Dispatch, SetStateAction } from "react";
import type { ListTasksParams, Task } from "../api/types";
import { formatDate, gateLabel } from "../i18n";
import { StatusBadge } from "./StatusBadge";

const STATUS_GROUPS: { label: string; value: string }[] = [
  { label: "Все", value: "" },
  { label: "Требуют решения", value: "pending_approvals" },
  { label: "Ожидают подтверждения", value: "group:awaiting" },
  { label: "В работе", value: "group:progress" },
  { label: "Нужны правки", value: "group:changes" },
  { label: "С ошибками", value: "group:failed" },
  { label: "Закрытые", value: "closed" },
  { label: "Отмененные", value: "cancelled" },
];

interface TaskListProps {
  advancedUi: boolean;
  filters: ListTasksParams;
  onSelectTask: (taskId: string) => void;
  onSetFilters: Dispatch<SetStateAction<ListTasksParams>>;
  selectedTaskId: string | null;
  tasks: Task[];
  total: number;
}

export function TaskList({ advancedUi, filters, onSelectTask, onSetFilters, selectedTaskId, tasks, total }: TaskListProps) {
  return (
    <section className="panel task-list-panel">
      <div className="section-title">
        <h2>Задачи</h2>
        <span>{total}</span>
      </div>
      <div className="filters">
        <label className="field-label">
          <span>Статус</span>
          <select
            value={filters.status || ""}
            onChange={(event) => onSetFilters((current) => ({ ...current, status: event.target.value || undefined }))}
          >
            {STATUS_GROUPS.map((group) => (
              <option key={group.value} value={group.value}>
                {group.label}
              </option>
            ))}
          </select>
        </label>
        {advancedUi ? (
          <>
            <label className="field-label">
              <span>Проект</span>
              <input
                value={filters.project_id || ""}
                onChange={(event) => onSetFilters((current) => ({ ...current, project_id: event.target.value || undefined }))}
                placeholder="project_id"
              />
            </label>
            <label className="field-label">
              <span>Сценарий работы</span>
              <input
                value={filters.workflow_id || ""}
                onChange={(event) => onSetFilters((current) => ({ ...current, workflow_id: event.target.value || undefined }))}
                placeholder="workflow_id"
              />
            </label>
          </>
        ) : null}
        <label className="field-label">
          <span>Поиск</span>
          <input
            value={filters.q || ""}
            onChange={(event) => onSetFilters((current) => ({ ...current, q: event.target.value || undefined }))}
            placeholder="Текст задачи"
          />
        </label>
      </div>
      <div className="task-list">
        {tasks.length === 0 ? <div className="empty">Задач пока нет. Создайте первую задачу.</div> : null}
        {tasks.map((task) => (
          <button
            className={task.id === selectedTaskId ? "task-list-item task-list-item--selected" : "task-list-item"}
            key={task.id}
            type="button"
            onClick={() => onSelectTask(task.id)}
          >
            <div className="task-list-item__top">
              <strong>{task.user_message || "Задача без описания"}</strong>
              <StatusBadge status={task.status} />
            </div>
            {task.current_approval_gate ? <span className="pending-pill">Требуется подтверждение: {gateLabel(task.current_approval_gate)}</span> : null}
            <div className="task-list-item__meta">
              <span>Обновлено: {formatDate(task.updated_at)}</span>
              <span>{task.project_name || task.workflow_name || "Маршрут будет выбран автоматически"}</span>
            </div>
            {advancedUi ? (
              <div className="task-list-item__meta task-list-item__meta--technical">
                <span>ID: {task.id}</span>
                <span>
                  {task.project_id || "project_id нет"} / {task.workflow_id || "workflow_id нет"}
                </span>
              </div>
            ) : null}
          </button>
        ))}
      </div>
    </section>
  );
}
