import { useState } from "react";
import { Check, X } from "lucide-react";
import { decideApproval } from "../api/client";
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
  const [loading, setLoading] = useState<"approve" | "reject" | null>(null);
  const pending = approvals.find((approval) => approval.status === "pending") || null;

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
            Approving this gate can immediately open the next required gate.
          </p>
          <pre className="json-block">{JSON.stringify(pending.requested_payload, null, 2)}</pre>
          <textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="comment" rows={4} />
          <div className="button-row">
            <button type="button" disabled={busy === "approval" || loading !== null} onClick={() => void decide("approve")}>
              <Check size={16} />
              {loading === "approve" ? "Approving..." : "Approve"}
            </button>
            <button type="button" disabled={busy === "approval" || loading !== null} onClick={() => void decide("reject")}>
              <X size={16} />
              {loading === "reject" ? "Rejecting..." : "Reject with comment"}
            </button>
          </div>
        </>
      ) : (
        <div className="empty">No pending approval.</div>
      )}
    </section>
  );
}
