import type { Dispatch, SetStateAction } from "react";
import type { ListTasksParams, Task } from "../api/types";
import { StatusBadge } from "./StatusBadge";

const STATUS_GROUPS: { label: string; value: string }[] = [
  { label: "All", value: "" },
  { label: "Pending approvals", value: "pending_approvals" },
  { label: "Awaiting approval", value: "group:awaiting" },
  { label: "In progress", value: "group:progress" },
  { label: "Changes requested", value: "group:changes" },
  { label: "Failed", value: "group:failed" },
  { label: "Closed", value: "closed" },
  { label: "Cancelled", value: "cancelled" },
];

interface TaskListProps {
  filters: ListTasksParams;
  onSelectTask: (taskId: string) => void;
  onSetFilters: Dispatch<SetStateAction<ListTasksParams>>;
  selectedTaskId: string | null;
  tasks: Task[];
  total: number;
}

export function TaskList({ filters, onSelectTask, onSetFilters, selectedTaskId, tasks, total }: TaskListProps) {
  return (
    <section className="panel task-list-panel">
      <div className="section-title">
        <h2>Tasks</h2>
        <span>{total}</span>
      </div>
      <div className="filters">
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
        <input
          value={filters.project_id || ""}
          onChange={(event) => onSetFilters((current) => ({ ...current, project_id: event.target.value || undefined }))}
          placeholder="project_id"
        />
        <input
          value={filters.workflow_id || ""}
          onChange={(event) => onSetFilters((current) => ({ ...current, workflow_id: event.target.value || undefined }))}
          placeholder="workflow_id"
        />
        <input
          value={filters.q || ""}
          onChange={(event) => onSetFilters((current) => ({ ...current, q: event.target.value || undefined }))}
          placeholder="search"
        />
      </div>
      <div className="task-list">
        {tasks.length === 0 ? <div className="empty">No tasks found.</div> : null}
        {tasks.map((task) => (
          <button
            className={task.id === selectedTaskId ? "task-list-item task-list-item--selected" : "task-list-item"}
            key={task.id}
            type="button"
            onClick={() => onSelectTask(task.id)}
          >
            <div className="task-list-item__top">
              <strong>{task.id}</strong>
              <StatusBadge status={task.status} />
            </div>
            <p>{task.user_message}</p>
            <div className="task-list-item__meta">
              <span>{task.project_id || "unknown project"}</span>
              <span>{task.workflow_id || "unknown workflow"}</span>
            </div>
            <div className="task-list-item__meta">
              <span>{formatDate(task.updated_at)}</span>
              {task.current_approval_gate ? <span>gate: {task.current_approval_gate}</span> : null}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "unknown";
}
