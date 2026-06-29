import { useCallback, useEffect, useMemo, useState } from "react";
import {
  cancelTask,
  createTask,
  getHealth,
  getTask,
  listApprovals,
  listTasks,
  routeTask,
  sendTaskMessage,
} from "./api/client";
import type { Approval, ListTasksParams, RouteDecision, Task } from "./api/types";
import { AppShell, type AppView } from "./components/AppShell";
import { ConfigEditor } from "./components/ConfigEditor";
import { RoutingRulesSettings } from "./components/RoutingRulesSettings";
import { TaskCreateForm } from "./components/TaskCreateForm";
import { TaskDetail } from "./components/TaskDetail";
import { TaskList } from "./components/TaskList";

const POLL_INTERVAL_MS = Number(import.meta.env.VITE_POLL_INTERVAL_MS || 3000);
const STATUS_GROUPS: Record<string, string[]> = {
  "group:awaiting": [
    "awaiting_plan_approval",
    "awaiting_spec_approval",
    "awaiting_config_approval",
    "awaiting_migration_approval",
    "awaiting_security_approval",
    "awaiting_diff_approval",
    "awaiting_correction_diff_approval",
    "awaiting_commit_approval",
    "awaiting_deploy_approval",
  ],
  "group:progress": [
    "created",
    "routing",
    "routed",
    "planning",
    "approved_for_execution",
    "preparing_worktree",
    "executing",
    "executing_correction",
    "validating",
    "validating_correction",
    "reviewing",
    "committing",
    "deploy_prep",
  ],
  "group:changes": ["plan_rejected", "changes_requested", "prompt_too_large", "awaiting_clarification", "correction_blocked"],
  "group:failed": ["failed", "validation_failed"],
};

export default function App() {
  const [apiHealthy, setApiHealthy] = useState(false);
  const [view, setView] = useState<AppView>(() => viewFromPath(window.location.pathname));
  const [tasks, setTasks] = useState<Task[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [routePreview, setRoutePreview] = useState<RouteDecision | null>(null);
  const [filters, setFilters] = useState<ListTasksParams>({ limit: 50, offset: 0 });
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const localStatusFilter = useMemo(() => filters.status || "", [filters.status]);

  const loadHealth = useCallback(async () => {
    try {
      const health = await getHealth();
      setApiHealthy(Boolean(health.ok));
    } catch {
      setApiHealthy(false);
    }
  }, []);

  const loadTasks = useCallback(async () => {
    const params = { ...filters };
    if (params.status?.startsWith("group:") || params.status === "pending_approvals") {
      delete params.status;
    }
    const response = await listTasks(params);
    let items = response.items;
    if (localStatusFilter === "pending_approvals") {
      items = items.filter((task) => task.current_approval_gate);
    } else if (localStatusFilter.startsWith("group:")) {
      const allowed = STATUS_GROUPS[localStatusFilter] || [];
      items = items.filter((task) => allowed.includes(String(task.status)));
    }
    setTasks(items);
    setTotal(localStatusFilter ? items.length : response.total);
    if (!selectedTaskId && items.length > 0) {
      setSelectedTaskId(items[0].id);
    }
  }, [filters, localStatusFilter, selectedTaskId]);

  const loadSelectedTask = useCallback(async () => {
    if (!selectedTaskId) {
      setSelectedTask(null);
      setApprovals([]);
      return;
    }
    const [task, approvalsResponse] = await Promise.all([getTask(selectedTaskId), listApprovals(selectedTaskId)]);
    const pendingGate = approvalsResponse.items.find((approval) => approval.status === "pending")?.gate ?? null;
    setSelectedTask({ ...task, current_approval_gate: pendingGate });
    setApprovals(approvalsResponse.items);
  }, [selectedTaskId]);

  const refresh = useCallback(async () => {
    try {
      await Promise.all([loadHealth(), loadTasks(), loadSelectedTask()]);
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось обновить данные");
    }
  }, [loadHealth, loadSelectedTask, loadTasks]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => setToast(null), 3500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    const onPopState = () => setView(viewFromPath(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  function navigate(nextView: AppView) {
    const nextPath = pathForView(nextView);
    if (window.location.pathname !== nextPath) {
      window.history.pushState({}, "", nextPath);
    }
    setView(nextView);
  }

  async function handlePreview(message: string) {
    setBusy("preview");
    try {
      setRoutePreview(await routeTask(message));
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось построить маршрут");
    } finally {
      setBusy(null);
    }
  }

  async function handleCreate(input: { message: string; source?: string | null; user_id?: string | null }) {
    setBusy("create");
    try {
      const response = await createTask(input);
      setSelectedTaskId(response.task_id);
      setToast(`Задача ${response.task_id} создана`);
      setRoutePreview(null);
      navigate("tasks");
      await refresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось создать задачу");
    } finally {
      setBusy(null);
    }
  }

  async function handleCorrection(message: string) {
    if (!selectedTaskId) {
      return;
    }
    setBusy("correction");
    try {
      const job = await sendTaskMessage(selectedTaskId, message);
      setToast(`Сообщение принято; ${job.action} в очереди`);
      await refresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось отправить сообщение");
    } finally {
      setBusy(null);
    }
  }

  async function handleCancel(comment: string) {
    if (!selectedTaskId) {
      return;
    }
    setBusy("cancel");
    try {
      await cancelTask(selectedTaskId, comment);
      setToast("Задача отменена");
      await refresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось отменить задачу");
    } finally {
      setBusy(null);
    }
  }

  return (
    <AppShell
      apiHealthy={apiHealthy}
      currentView={view}
      error={error}
      layoutMode={view === "tasks" ? "split" : "single"}
      toast={toast}
      onDismissError={() => setError(null)}
      onNavigate={navigate}
    >
      {view === "routing" ? (
        <RoutingRulesSettings setError={setError} setToast={setToast} />
      ) : null}
      {view === "config" ? <ConfigEditor setError={setError} setToast={setToast} /> : null}
      {view === "create" ? (
        <main className="main create-main">
          <TaskCreateForm
            busy={busy}
            layout="page"
            onCreate={handleCreate}
            onPreview={handlePreview}
            routePreview={routePreview}
          />
        </main>
      ) : null}
      {view === "tasks" ? (
        <>
          <aside className="sidebar">
            <TaskList
              filters={filters}
              onSelectTask={setSelectedTaskId}
              onSetFilters={setFilters}
              selectedTaskId={selectedTaskId}
              tasks={tasks}
              total={total}
            />
          </aside>
          <TaskDetail
            approvals={approvals}
            busy={busy}
            onCancel={handleCancel}
            onCorrection={handleCorrection}
            onRefresh={refresh}
            selectedTask={selectedTask}
            setError={setError}
            setToast={setToast}
          />
        </>
      ) : null}
    </AppShell>
  );
}

function viewFromPath(pathname: string): AppView {
  if (pathname === "/settings/routing-rules") return "routing";
  if (pathname === "/settings/config") return "config";
  if (pathname === "/tasks/new") return "create";
  if (pathname === "/tasks" || pathname.startsWith("/tasks/")) return "tasks";
  return "create";
}

function pathForView(view: AppView): string {
  if (view === "routing") return "/settings/routing-rules";
  if (view === "config") return "/settings/config";
  if (view === "tasks") return "/tasks";
  return "/tasks/new";
}
