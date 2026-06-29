import { useState } from "react";
import { Check, Play, ClipboardList, X } from "lucide-react";
import { createCorrection, decideApproval } from "../api/client";
import type { Approval } from "../api/types";
import { gateLabel, formatDate } from "../i18n";

interface ApprovalPanelProps {
  approvals: Approval[];
  busy: string | null;
  onRefresh: () => Promise<void>;
  setError: (message: string | null) => void;
  setToast: (message: string | null) => void;
  taskId: string;
}

const DANGEROUS_GATES = new Set(["diff", "commit", "config_change", "migration", "security_change", "deploy", "deploy_prep"]);

export function ApprovalPanel({ approvals, busy, onRefresh, setError, setToast, taskId }: ApprovalPanelProps) {
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
          ? `Вы разрешаете коммит для ${taskId}. Это может создать git commit в task worktree.`
          : `Вы подтверждаете gate ${pending.gate} для ${taskId}. Проверьте артефакты и результат валидации.`;
      if (!window.confirm(text)) return;
    }
    setLoading(decision);
    try {
      const job = await decideApproval(taskId, pending.gate, { decision, comment: comment.trim() || null });
      const action = decision === "approve" ? "подтвержден" : "отклонен";
      setToast(`${pending.gate} ${action}; ${job.action} в очереди`);
      setComment("");
      await onRefresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось выполнить approval-действие");
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
      const correction = await createCorrection(taskId, {
        source_gate: pending.gate,
        source_approval_id: pending.id,
        comment: comment.trim(),
        action,
      });
      setToast(
        action === "run_without_new_plan"
          ? `Запрос правки создан. Режим: ${correction.mode}.`
          : `Запрос правки создан. Режим: ${correction.mode}. Запрошено approval плана.`,
      );
      setComment("");
      await onRefresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось создать запрос правки");
    } finally {
      setLoading(null);
    }
  }

  return (
    <section className="panel">
      <h2>Approval</h2>
      {pending ? (
        <>
          <dl className="kv">
            <dt>gate</dt>
            <dd>{gateLabel(pending.gate)}</dd>
            <dt>status</dt>
            <dd>{pending.status}</dd>
            <dt>created_at</dt>
            <dd>{formatDate(pending.created_at)}</dd>
            <dt>artifact_ids</dt>
            <dd>{pending.artifact_ids.join(", ") || "нет"}</dd>
          </dl>
          <p className="approval-note">
            {isDiffGate
              ? "Комментарий к diff может стать основанием для точечной правки, если она не меняет объем задачи и не задевает рискованные области."
              : "Подтверждение gate может сразу открыть следующий обязательный этап."}
          </p>
          <pre className="json-block">{JSON.stringify(pending.requested_payload, null, 2)}</pre>
          <textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Комментарий" rows={4} />
          <div className="button-row">
            <button type="button" disabled={busy === "approval" || loading !== null} onClick={() => void decide("approve")}>
              <Check size={16} />
              {loading === "approve" ? "Подтверждаю..." : isDiffGate ? "Подтвердить diff" : "Подтвердить"}
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
        <div className="empty">Нет ожидающих approvals.</div>
      )}
    </section>
  );
}
