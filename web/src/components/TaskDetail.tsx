import { useState } from "react";
import type { Approval, Task } from "../api/types";
import { ActionPanel } from "./ActionPanel";
import { ApprovalPanel } from "./ApprovalPanel";
import { ApprovalsPanel } from "./ApprovalsPanel";
import { CorrectionPanel } from "./CorrectionPanel";
import { EventsPanel } from "./EventsPanel";
import { JobsPanel } from "./JobsPanel";
import { ModelPolicyPanel } from "./ModelPolicyPanel";
import { PromptReportPanel } from "./PromptReportPanel";
import { RunsPanel } from "./RunsPanel";
import { displayValue, gateLabel } from "../i18n";
import { StatusBadge } from "./StatusBadge";
import { TaskArtifacts } from "./TaskArtifacts";
import { TaskHeader } from "./TaskHeader";

type Tab = "overview" | "artifacts" | "approvals" | "events" | "runs" | "raw";

interface TaskDetailProps {
  approvals: Approval[];
  busy: string | null;
  onCancel: (comment: string) => Promise<void>;
  onCorrection: (message: string) => Promise<void>;
  onRefresh: () => Promise<void>;
  selectedTask: Task | null;
  setError: (message: string | null) => void;
  setToast: (message: string | null) => void;
}

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Обзор" },
  { id: "artifacts", label: "Артефакты" },
  { id: "approvals", label: "Approvals" },
  { id: "events", label: "События" },
  { id: "runs", label: "Запуски" },
  { id: "raw", label: "JSON" },
];

export function TaskDetail({ approvals, busy, onCancel, onCorrection, onRefresh, selectedTask, setError, setToast }: TaskDetailProps) {
  const [tab, setTab] = useState<Tab>("overview");

  if (!selectedTask) {
    return (
      <main className="main empty-main">
        <div>Выберите или создайте задачу.</div>
      </main>
    );
  }

  const pendingApproval = approvals.find((approval) => approval.status === "pending") || null;
  const routeDecision = selectedTask.route_decision || {};
  const correctionMode = routeDecision.correction_mode || routeDecision.task_kind;
  const manualReviewRequired =
    routeDecision.manual_review_required === true ||
    routeDecision.planning_mode === "degraded_no_mcp" ||
    routeDecision.validation_warning === "manual_review_required";

  return (
    <main className="main">
      <TaskHeader busy={busy} onCancel={onCancel} task={selectedTask} />
      <div className="tabs">
        {TABS.map((item) => (
          <button className={tab === item.id ? "tab tab--active" : "tab"} key={item.id} type="button" onClick={() => setTab(item.id)}>
            {item.label}
          </button>
        ))}
      </div>
      {tab === "overview" ? (
        <section className="detail-grid">
          <div className="panel overview">
            <h2>Обзор</h2>
            <p className="message">{selectedTask.user_message}</p>
            <dl className="kv">
              <dt>Статус</dt>
              <dd>
                <StatusBadge status={selectedTask.status} />
              </dd>
              <dt>Текущий gate</dt>
              <dd>{gateLabel(pendingApproval?.gate)}</dd>
              <dt>Маршрут</dt>
              <dd>
                {displayValue(selectedTask.project_id)} / {displayValue(selectedTask.workflow_id)}
              </dd>
              <dt>Родительская задача</dt>
              <dd>{displayValue(selectedTask.parent_task_id)}</dd>
              <dt>Правка</dt>
              <dd>
                {selectedTask.correction_source
                  ? `${String(correctionMode || "correction")} / ${selectedTask.correction_source}`
                  : "нет"}
              </dd>
              <dt>Риск</dt>
              <dd>{displayValue(selectedTask.risk_level)}</dd>
            </dl>
            {selectedTask.workflow_id === "task_correction" ? (
              <p className="task-header__warning">
                Полный план не требуется. Финальное approval diff все равно останется обязательным.
              </p>
            ) : null}
            {manualReviewRequired ? (
              <p className="task-header__warning">1C-проверка пропущена. Нужна ручная проверка.</p>
            ) : null}
            <h3>Решение маршрутизатора</h3>
            <pre className="json-block">{JSON.stringify(routeDecision, null, 2)}</pre>
          </div>
          <div className="action-stack">
            <ActionPanel
              busy={busy}
              onRefresh={onRefresh}
              setError={setError}
              setToast={setToast}
              task={selectedTask}
            />
            <ApprovalPanel
              approvals={approvals}
              busy={busy}
              onRefresh={onRefresh}
              setError={setError}
              setToast={setToast}
              taskId={selectedTask.id}
            />
            <CorrectionPanel busy={busy} onCorrection={onCorrection} task={selectedTask} />
            <JobsPanel setError={setError} taskId={selectedTask.id} />
            <ModelPolicyPanel setError={setError} taskId={selectedTask.id} />
            <PromptReportPanel setError={setError} taskId={selectedTask.id} />
          </div>
        </section>
      ) : null}
      {tab === "artifacts" ? <TaskArtifacts setError={setError} taskId={selectedTask.id} /> : null}
      {tab === "approvals" ? <ApprovalsPanel approvals={approvals} /> : null}
      {tab === "events" ? <EventsPanel setError={setError} taskId={selectedTask.id} /> : null}
      {tab === "runs" ? <RunsPanel setError={setError} taskId={selectedTask.id} /> : null}
      {tab === "raw" ? <pre className="json-block raw-json">{JSON.stringify(selectedTask, null, 2)}</pre> : null}
    </main>
  );
}
