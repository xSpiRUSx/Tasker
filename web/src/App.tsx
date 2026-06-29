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
import { AppShell } from "./components/AppShell";
import { RoutingRulesSettings } from "./components/RoutingRulesSettings";
import { Sidebar } from "./components/Sidebar";
import { TaskDetail } from "./components/TaskDetail";

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
  const isRoutingSettings = window.location.pathname === "/settings/routing-rules";

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
      setError(error instanceof Error ? error.message : "Refresh failed");
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

  async function handlePreview(message: string) {
    setBusy("preview");
    try {
      setRoutePreview(await routeTask(message));
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Route preview failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleCreate(input: { message: string; source?: string | null; user_id?: string | null }) {
    setBusy("create");
    try {
      const response = await createTask(input);
      setSelectedTaskId(response.task_id);
      setToast(`Task ${response.task_id} created`);
      setRoutePreview(null);
      await refresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Task creation failed");
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
      setToast(`Message accepted; ${job.action} queued`);
      await refresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Message send failed");
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
      setToast("Task cancelled");
      await refresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Cancel failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <AppShell apiHealthy={apiHealthy} error={error} toast={toast} onDismissError={() => setError(null)}>
      {isRoutingSettings ? (
        <RoutingRulesSettings setError={setError} setToast={setToast} />
      ) : (
        <>
          <Sidebar
            busy={busy}
            filters={filters}
            onCreate={handleCreate}
            onPreview={handlePreview}
            onSelectTask={setSelectedTaskId}
            onSetFilters={setFilters}
            routePreview={routePreview}
            selectedTaskId={selectedTaskId}
            tasks={tasks}
            total={total}
          />
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
      )}
    </AppShell>
  );
}
