import { useState } from "react";
import { Check, Play, ClipboardList, X } from "lucide-react";
import { createCorrection, decideApproval } from "../api/client";
import type { Approval } from "../api/types";

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
      setError("Reject requires a non-empty comment.");
      return;
    }
    if (decision === "approve" && DANGEROUS_GATES.has(pending.gate)) {
      const text =
        pending.gate === "commit"
          ? `You are approving commit for ${taskId}. This may create a git commit in the task worktree.`
          : `You are approving the ${pending.gate} gate for ${taskId}. Make sure you reviewed artifacts and validation output.`;
      if (!window.confirm(text)) return;
    }
    setLoading(decision);
    try {
      const job = await decideApproval(taskId, pending.gate, { decision, comment: comment.trim() || null });
      const action = decision === "approve" ? "approved" : "rejected";
      setToast(`${pending.gate} ${action}; ${job.action} queued`);
      setComment("");
      await onRefresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Approval action failed");
    } finally {
      setLoading(null);
    }
  }

  async function requestCorrection(action: "run_without_new_plan" | "show_plan_first") {
    if (!pending) return;
    if (!comment.trim()) {
      setError("Request changes requires a non-empty comment.");
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
          ? `Correction request created. Mode: ${correction.mode}. Approval already granted by your review comment.`
          : `Correction request created. Mode: ${correction.mode}. Plan approval requested.`,
      );
      setComment("");
      await onRefresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Correction request failed");
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
            <dd>{pending.gate}</dd>
            <dt>status</dt>
            <dd>{pending.status}</dd>
            <dt>created_at</dt>
            <dd>{new Date(pending.created_at).toLocaleString()}</dd>
            <dt>artifact_ids</dt>
            <dd>{pending.artifact_ids.join(", ") || "none"}</dd>
          </dl>
          <p className="approval-note">
            {isDiffGate
              ? "A diff review comment is approval to apply that focused correction unless it changes scope or touches risky areas."
              : "Approving this gate can immediately open the next required gate."}
          </p>
          <pre className="json-block">{JSON.stringify(pending.requested_payload, null, 2)}</pre>
          <textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="comment" rows={4} />
          <div className="button-row">
            <button type="button" disabled={busy === "approval" || loading !== null} onClick={() => void decide("approve")}>
              <Check size={16} />
              {loading === "approve" ? "Approving..." : isDiffGate ? "Approve diff" : "Approve"}
            </button>
            {isDiffGate ? (
              <>
                <button type="button" disabled={busy === "approval" || loading !== null} onClick={() => void requestCorrection("run_without_new_plan")}>
                  <Play size={16} />
                  {loading === "run" ? "Requesting..." : "Request changes & run"}
                </button>
                <button type="button" disabled={busy === "approval" || loading !== null} onClick={() => void requestCorrection("show_plan_first")}>
                  <ClipboardList size={16} />
                  {loading === "plan" ? "Requesting..." : "Request changes, but show plan first"}
                </button>
              </>
            ) : (
              <button type="button" disabled={busy === "approval" || loading !== null} onClick={() => void decide("reject")}>
                <X size={16} />
                {loading === "reject" ? "Requesting..." : "Request changes"}
              </button>
            )}
          </div>
        </>
      ) : (
        <div className="empty">No pending approval.</div>
      )}
    </section>
  );
}
