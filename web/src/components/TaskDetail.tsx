import { useMemo, useState } from "react";
import type { Approval, Task } from "../api/types";
import { displayValue, gateLabel, riskLabel } from "../i18n";
import { ActionPanel } from "./ActionPanel";
import { AdvancedSection } from "./AdvancedSection";
import { ApprovalPanel } from "./ApprovalPanel";
import { ApprovalsPanel } from "./ApprovalsPanel";
import { CorrectionPanel } from "./CorrectionPanel";
import { EventsPanel } from "./EventsPanel";
import { JobsPanel } from "./JobsPanel";
import { ModelPolicyPanel } from "./ModelPolicyPanel";
import { PromptReportPanel } from "./PromptReportPanel";
import { RunsPanel } from "./RunsPanel";
import { StatusBadge } from "./StatusBadge";
import { TaskArtifacts } from "./TaskArtifacts";
import { TaskHeader } from "./TaskHeader";

type Tab = "overview" | "artifacts" | "approvals" | "events" | "runs" | "raw";

interface TaskDetailProps {
  advancedUi: boolean;
  approvals: Approval[];
  busy: string | null;
  onCancel: (comment: string) => Promise<void>;
  onCorrection: (message: string) => Promise<void>;
  onRefresh: () => Promise<void>;
  selectedTask: Task | null;
  setError: (message: string | null) => void;
  setToast: (message: string | null) => void;
}

const BASE_TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Обзор" },
  { id: "artifacts", label: "Артефакты" },
  { id: "approvals", label: "Подтверждения" },
];

const ADVANCED_TABS: { id: Tab; label: string }[] = [
  { id: "events", label: "События" },
  { id: "runs", label: "Запуски" },
  { id: "raw", label: "JSON" },
];

export function TaskDetail({
  advancedUi,
  approvals,
  busy,
  onCancel,
  onCorrection,
  onRefresh,
  selectedTask,
  setError,
  setToast,
}: TaskDetailProps) {
  const [tab, setTab] = useState<Tab>("overview");
  const tabs = useMemo(() => (advancedUi ? [...BASE_TABS, ...ADVANCED_TABS] : BASE_TABS), [advancedUi]);
  const activeTab = tabs.some((item) => item.id === tab) ? tab : "overview";

  if (!selectedTask) {
    return (
      <main className="main empty-main">
        <div>Выберите или создайте задачу.</div>
      </main>
    );
  }

  const pendingApproval = approvals.find((approval) => approval.status === "pending") || null;
  const routeDecision = selectedTask.route_decision || {};
  const manualReviewRequired =
    routeDecision.manual_review_required === true ||
    routeDecision.planning_mode === "degraded_no_mcp" ||
    routeDecision.validation_warning === "manual_review_required";
  const packageStatus = routeDecision.package_status ? String(routeDecision.package_status) : null;

  return (
    <main className="main">
      <TaskHeader advancedUi={advancedUi} busy={busy} onCancel={onCancel} task={selectedTask} />
      <div className="tabs">
        {tabs.map((item) => (
          <button className={activeTab === item.id ? "tab tab--active" : "tab"} key={item.id} type="button" onClick={() => setTab(item.id)}>
            {item.label}
          </button>
        ))}
      </div>
      {activeTab === "overview" ? (
        <section className="detail-grid">
          <div className="panel overview">
            <h2>Обзор</h2>
            <p className="message">{selectedTask.user_message}</p>
            <dl className="kv">
              <dt>Статус</dt>
              <dd>
                <StatusBadge status={selectedTask.status} />
              </dd>
              <dt>Текущее подтверждение</dt>
              <dd>{pendingApproval ? gateLabel(pendingApproval.gate) : "сейчас подтверждения не требуются"}</dd>
              <dt>Проект</dt>
              <dd>{displayValue(selectedTask.project_name || (selectedTask.project_id ? "проект выбран" : null))}</dd>
              <dt>Сценарий работы</dt>
              <dd>{displayValue(selectedTask.workflow_name || (selectedTask.workflow_id ? "сценарий выбран" : null))}</dd>
              <dt>Риск</dt>
              <dd>{riskLabel(selectedTask.risk_level)}</dd>
            </dl>

            {selectedTask.workflow_id === "task_correction" ? (
              <p className="task-header__warning">
                Для этой правки полный новый план не требуется. Итоговые изменения все равно нужно будет подтвердить.
              </p>
            ) : null}
            {manualReviewRequired ? (
              <p className="task-header__warning">Автоматическая проверка пропущена. Перед продолжением нужна ручная проверка результата.</p>
            ) : null}
            {selectedTask.status === "awaiting_tool_health_override" ? (
              <p className="task-header__warning">Один из инструментов недоступен. Продолжайте только после ручной проверки.</p>
            ) : null}
            {selectedTask.status === "awaiting_scope_escalation_approval" ? (
              <p className="task-header__warning">Tasker обнаружил расширение объема работ. Требуется отдельное подтверждение.</p>
            ) : null}

            <AdvancedSection enabled={advancedUi}>
              {packageStatus ? (
                <p className="task-header__warning">
                  Output package: {packageStatus}. Manual build: {routeDecision.manual_build_required === true ? "yes" : "no"}.
                </p>
              ) : null}
              <h3>Технические данные маршрута</h3>
              <pre className="json-block">{JSON.stringify(routeDecision, null, 2)}</pre>
            </AdvancedSection>
          </div>
          <div className="action-stack">
            <ApprovalPanel
              advancedUi={advancedUi}
              approvals={approvals}
              busy={busy}
              onRefresh={onRefresh}
              setError={setError}
              setToast={setToast}
              taskId={selectedTask.id}
            />
            <CorrectionPanel busy={busy} onCorrection={onCorrection} task={selectedTask} />
            <AdvancedSection enabled={advancedUi}>
              <ActionPanel
                busy={busy}
                onRefresh={onRefresh}
                setError={setError}
                setToast={setToast}
                task={selectedTask}
              />
              <JobsPanel setError={setError} taskId={selectedTask.id} />
              <ModelPolicyPanel setError={setError} taskId={selectedTask.id} />
              <PromptReportPanel setError={setError} taskId={selectedTask.id} />
            </AdvancedSection>
          </div>
        </section>
      ) : null}
      {activeTab === "artifacts" ? <TaskArtifacts advancedUi={advancedUi} setError={setError} taskId={selectedTask.id} /> : null}
      {activeTab === "approvals" ? <ApprovalsPanel advancedUi={advancedUi} approvals={approvals} /> : null}
      {advancedUi && activeTab === "events" ? <EventsPanel setError={setError} taskId={selectedTask.id} /> : null}
      {advancedUi && activeTab === "runs" ? <RunsPanel setError={setError} taskId={selectedTask.id} /> : null}
      {advancedUi && activeTab === "raw" ? <pre className="json-block raw-json">{JSON.stringify(selectedTask, null, 2)}</pre> : null}
    </main>
  );
}
