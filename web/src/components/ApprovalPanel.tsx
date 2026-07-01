import { useState } from "react";
import { Check, ClipboardList, Play, X } from "lucide-react";
import { createCorrection, decideApproval } from "../api/client";
import type { Approval } from "../api/types";
import { formatDate, gateLabel, statusLabel } from "../i18n";
import { AdvancedSection } from "./AdvancedSection";

interface ApprovalPanelProps {
  advancedUi: boolean;
  approvals: Approval[];
  busy: string | null;
  onRefresh: () => Promise<void>;
  setError: (message: string | null) => void;
  setToast: (message: string | null) => void;
  taskId: string;
}

const DANGEROUS_GATES = new Set([
  "diff",
  "commit",
  "config_change",
  "migration",
  "security_change",
  "deploy",
  "deploy_prep",
  "tool_health_override",
  "scope_escalation",
]);

export function ApprovalPanel({ advancedUi, approvals, busy, onRefresh, setError, setToast, taskId }: ApprovalPanelProps) {
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState<"approve" | "reject" | "run" | "plan" | null>(null);
  const pending = approvals.find((approval) => approval.status === "pending") || null;
  const isDiffGate = pending?.gate === "diff";

  async function decide(decision: "approve" | "reject") {
    if (!pending) return;
    if (decision === "reject" && !comment.trim()) {
      setError("Для запроса правок нужен комментарий.");
      return;
    }
    if (decision === "approve" && DANGEROUS_GATES.has(pending.gate)) {
      const text =
        pending.gate === "commit"
          ? "Вы разрешаете зафиксировать изменения. Проверьте артефакты и результат проверки."
          : `Вы подтверждаете этап: ${gateLabel(pending.gate)}. Проверьте артефакты и результат проверки.`;
      if (!window.confirm(text)) return;
    }
    setLoading(decision);
    try {
      await decideApproval(taskId, pending.gate, { decision, comment: comment.trim() || null });
      setToast(decision === "approve" ? "Подтверждение принято" : "Запрос правок принят");
      setComment("");
      await onRefresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось выполнить действие подтверждения.");
    } finally {
      setLoading(null);
    }
  }

  async function requestCorrection(action: "run_without_new_plan" | "show_plan_first") {
    if (!pending) return;
    if (!comment.trim()) {
      setError("Для запроса правок нужен комментарий.");
      return;
    }
    const loadingKey = action === "run_without_new_plan" ? "run" : "plan";
    setLoading(loadingKey);
    try {
      await createCorrection(taskId, {
        source_gate: pending.gate,
        source_approval_id: pending.id,
        comment: comment.trim(),
        action,
      });
      setToast(action === "run_without_new_plan" ? "Запрос правки создан" : "Запрос правки с новым планом создан");
      setComment("");
      await onRefresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось создать запрос правки.");
    } finally {
      setLoading(null);
    }
  }

  return (
    <section className="panel">
      <h2>Подтверждение</h2>
      {pending ? (
        <>
          <div className="approval-summary">
            <strong>Требуется подтверждение: {gateLabel(pending.gate)}</strong>
            <span>Проверьте артефакты и выберите действие.</span>
          </div>
          <AdvancedSection enabled={advancedUi}>
            <dl className="kv">
              <dt>Этап подтверждения</dt>
              <dd>{gateLabel(pending.gate)}</dd>
              <dt>Статус</dt>
              <dd>{statusLabel(pending.status)}</dd>
              <dt>Создано</dt>
              <dd>{formatDate(pending.created_at)}</dd>
              <dt>ID</dt>
              <dd>{pending.id}</dd>
              <dt>Связанные артефакты</dt>
              <dd>{pending.artifact_ids.join(", ") || "нет"}</dd>
            </dl>
          </AdvancedSection>
          <p className="approval-note">
            {isDiffGate
              ? "Комментарий к изменениям можно использовать как запрос точечной правки."
              : "После подтверждения Tasker перейдет к следующему этапу."}
          </p>
          <AdvancedSection enabled={advancedUi}>
            <h3>Технические данные запроса</h3>
            <pre className="json-block">{JSON.stringify(pending.requested_payload, null, 2)}</pre>
          </AdvancedSection>
          <label className="field-label">
            <span>Комментарий</span>
            <textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Что нужно изменить или проверить" rows={4} />
          </label>
          <div className="button-row">
            <button type="button" disabled={busy === "approval" || loading !== null} onClick={() => void decide("approve")}>
              <Check size={16} />
              {loading === "approve" ? "Подтверждаю..." : isDiffGate ? "Подтвердить изменения" : "Подтвердить"}
            </button>
            {isDiffGate ? (
              <>
                <button type="button" disabled={busy === "approval" || loading !== null} onClick={() => void requestCorrection("run_without_new_plan")}>
                  <Play size={16} />
                  {loading === "run" ? "Запрашиваю..." : "Правки и запуск"}
                </button>
                <button type="button" disabled={busy === "approval" || loading !== null} onClick={() => void requestCorrection("show_plan_first")}>
                  <ClipboardList size={16} />
                  {loading === "plan" ? "Запрашиваю..." : "Правки с новым планом"}
                </button>
              </>
            ) : (
              <button type="button" disabled={busy === "approval" || loading !== null} onClick={() => void decide("reject")}>
                <X size={16} />
                {loading === "reject" ? "Запрашиваю..." : "Запросить правки"}
              </button>
            )}
          </div>
        </>
      ) : (
        <div className="empty">Сейчас подтверждения не требуются.</div>
      )}
    </section>
  );
}
