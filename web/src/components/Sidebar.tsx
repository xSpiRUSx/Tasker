import type { Dispatch, SetStateAction } from "react";
import type { ListTasksParams, RouteDecision, Task } from "../api/types";
import { TaskCreateForm } from "./TaskCreateForm";
import { TaskList } from "./TaskList";

interface SidebarProps {
  busy: string | null;
  filters: ListTasksParams;
  onCreate: (input: { message: string; source?: string | null; user_id?: string | null }) => Promise<void>;
  onPreview: (message: string) => Promise<void>;
  onSelectTask: (taskId: string) => void;
  onSetFilters: Dispatch<SetStateAction<ListTasksParams>>;
  routePreview: RouteDecision | null;
  selectedTaskId: string | null;
  tasks: Task[];
  total: number;
}

export function Sidebar(props: SidebarProps) {
  return (
    <aside className="sidebar">
      <TaskCreateForm
        busy={props.busy}
        onCreate={props.onCreate}
        onPreview={props.onPreview}
        routePreview={props.routePreview}
      />
      <TaskList
        filters={props.filters}
        onSelectTask={props.onSelectTask}
        onSetFilters={props.onSetFilters}
        selectedTaskId={props.selectedTaskId}
        tasks={props.tasks}
        total={props.total}
      />
    </aside>
  );
}
