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
import { SettingsPanel } from "./components/SettingsPanel";
import { TaskCreateForm } from "./components/TaskCreateForm";
import { TaskDetail } from "./components/TaskDetail";
import { TaskList } from "./components/TaskList";
import { isAdvancedUiEnabled, setAdvancedUiEnabled } from "./uiMode";
import { userFacingError } from "./i18n";

const POLL_INTERVAL_MS = Number(import.meta.env.VITE_POLL_INTERVAL_MS || 3000);
const ADVANCED_FORCED = import.meta.env.VITE_TASKER_ADVANCED_UI === "true";

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
  const [advancedUi, setAdvancedUi] = useState(() => isAdvancedUiEnabled());
  const [apiHealthy, setApiHealthy] = useState(false);
  const [view, setView] = useState<AppView>(() => viewFromPath(window.location.pathname, isAdvancedUiEnabled()));
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
    if (!advancedUi) {
      delete params.project_id;
      delete params.workflow_id;
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
  }, [advancedUi, filters, localStatusFilter, selectedTaskId]);

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
      setError(advancedUi && error instanceof Error ? error.message : userFacingError());
    }
  }, [advancedUi, loadHealth, loadSelectedTask, loadTasks]);

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
    const onPopState = () => setView(viewFromPath(window.location.pathname, advancedUi));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [advancedUi]);

  function navigate(nextView: AppView) {
    const safeView = !advancedUi && (nextView === "config" || nextView === "routing") ? "settings" : nextView;
    const nextPath = pathForView(safeView);
    if (window.location.pathname !== nextPath) {
      window.history.pushState({}, "", nextPath);
    }
    setView(safeView);
  }

  function handleAdvancedUiChange(value: boolean) {
    const nextValue = ADVANCED_FORCED ? true : value;
    setAdvancedUiEnabled(nextValue);
    setAdvancedUi(nextValue);
    if (!nextValue && (view === "config" || view === "routing")) {
      navigate("settings");
    }
  }

  async function handlePreview(message: string) {
    setBusy("preview");
    try {
      setRoutePreview(await routeTask(message));
      setError(null);
    } catch (error) {
      setError(advancedUi && error instanceof Error ? error.message : "Не удалось проверить маршрут задачи.");
    } finally {
      setBusy(null);
    }
  }

  async function handleCreate(input: { message: string; source?: string | null; user_id?: string | null }) {
    setBusy("create");
    try {
      const response = await createTask(input);
      setSelectedTaskId(response.task_id);
      setToast("Задача создана");
      setRoutePreview(null);
      navigate("tasks");
      await refresh();
    } catch (error) {
      setError(advancedUi && error instanceof Error ? error.message : "Не удалось создать задачу. Проверьте подключение к серверу.");
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
      await sendTaskMessage(selectedTaskId, message);
      setToast("Сообщение принято, Tasker поставил действие в очередь");
      await refresh();
    } catch (error) {
      setError(advancedUi && error instanceof Error ? error.message : "Не удалось отправить сообщение.");
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
      setError(advancedUi && error instanceof Error ? error.message : "Не удалось отменить задачу.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <AppShell
      advancedUi={advancedUi}
      apiHealthy={apiHealthy}
      currentView={view}
      error={error}
      layoutMode={view === "tasks" ? "split" : "single"}
      toast={toast}
      onDismissError={() => setError(null)}
      onNavigate={navigate}
    >
      {view === "settings" ? (
        <SettingsPanel advancedUi={advancedUi} onAdvancedUiChange={handleAdvancedUiChange} onNavigate={navigate} />
      ) : null}
      {advancedUi && view === "routing" ? <RoutingRulesSettings setError={setError} setToast={setToast} /> : null}
      {advancedUi && view === "config" ? <ConfigEditor setError={setError} setToast={setToast} /> : null}
      {view === "create" ? (
        <main className="main create-main">
          <TaskCreateForm
            advancedUi={advancedUi}
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
              advancedUi={advancedUi}
              filters={filters}
              onSelectTask={setSelectedTaskId}
              onSetFilters={setFilters}
              selectedTaskId={selectedTaskId}
              tasks={tasks}
              total={total}
            />
          </aside>
          <TaskDetail
            advancedUi={advancedUi}
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

function viewFromPath(pathname: string, advancedUi: boolean): AppView {
  if (advancedUi && pathname === "/settings/routing-rules") return "routing";
  if (advancedUi && pathname === "/settings/config") return "config";
  if (pathname === "/settings") return "settings";
  if (pathname === "/tasks/new") return "create";
  if (pathname === "/tasks" || pathname.startsWith("/tasks/")) return "tasks";
  return "create";
}

function pathForView(view: AppView): string {
  if (view === "routing") return "/settings/routing-rules";
  if (view === "config") return "/settings/config";
  if (view === "settings") return "/settings";
  if (view === "tasks") return "/tasks";
  return "/tasks/new";
}
