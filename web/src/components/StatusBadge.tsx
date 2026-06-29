import { statusLabel } from "../i18n";

interface StatusBadgeProps {
  status?: string | null;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const value = status || "unknown";
  return <span className={`status-badge ${classNameForStatus(value)}`}>{statusLabel(value)}</span>;
}

function classNameForStatus(status: string): string {
  if (status.startsWith("awaiting_")) return "status-badge--awaiting";
  if (["executing", "executing_correction", "validating", "validating_correction", "reviewing", "committing", "routing", "planning", "classifying_correction"].includes(status)) return "status-badge--active";
  if (status === "closed") return "status-badge--closed";
  if (status === "failed" || status === "validation_failed") return "status-badge--failed";
  if (status === "cancelled") return "status-badge--cancelled";
  if (status === "changes_requested" || status === "plan_rejected" || status === "prompt_too_large" || status === "correction_blocked") return "status-badge--changes";
  return "status-badge--neutral";
}
