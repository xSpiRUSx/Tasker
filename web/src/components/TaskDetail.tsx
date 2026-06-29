import { useState } from "react";
import type { Approval, Task } from "../api/types";
import { ApprovalPanel } from "./ApprovalPanel";
import { ApprovalsPanel } from "./ApprovalsPanel";
import { CorrectionPanel } from "./CorrectionPanel";
import { EventsPanel } from "./EventsPanel";
import { RunsPanel } from "./RunsPanel";
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
  { id: "overview", label: "Overview" },
  { id: "artifacts", label: "Artifacts" },
  { id: "approvals", label: "Approvals" },
  { id: "events", label: "Events" },
  { id: "runs", label: "Runs" },
  { id: "raw", label: "Raw JSON" },
];

export function TaskDetail({ approvals, busy, onCancel, onCorrection, onRefresh, selectedTask, setError, setToast }: TaskDetailProps) {
  const [tab, setTab] = useState<Tab>("overview");

  if (!selectedTask) {
    return (
      <main className="main empty-main">
        <div>Select or create a task.</div>
      </main>
    );
  }

  const pendingApproval = approvals.find((approval) => approval.status === "pending") || null;

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
            <h2>Overview</h2>
            <p className="message">{selectedTask.user_message}</p>
            <dl className="kv">
              <dt>Status</dt>
              <dd>
                <StatusBadge status={selectedTask.status} />
              </dd>
              <dt>Pending gate</dt>
              <dd>{pendingApproval?.gate || "none"}</dd>
              <dt>Route</dt>
              <dd>
                {selectedTask.project_id || "unknown"} / {selectedTask.workflow_id || "unknown"}
              </dd>
              <dt>Risk</dt>
              <dd>{selectedTask.risk_level || "unknown"}</dd>
            </dl>
            <h3>Route decision</h3>
            <pre className="json-block">{JSON.stringify(selectedTask.route_decision || {}, null, 2)}</pre>
          </div>
          <div className="action-stack">
            <ApprovalPanel
              approvals={approvals}
              busy={busy}
              onRefresh={onRefresh}
              setError={setError}
              setToast={setToast}
              taskId={selectedTask.id}
            />
            <CorrectionPanel busy={busy} onCorrection={onCorrection} task={selectedTask} />
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
