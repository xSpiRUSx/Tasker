import { useState } from "react";
import { Send } from "lucide-react";
import type { Task } from "../api/types";

interface CorrectionPanelProps {
  busy: string | null;
  onCorrection: (message: string) => Promise<void>;
  task: Task;
}

export function CorrectionPanel({ busy, onCorrection, task }: CorrectionPanelProps) {
  const [message, setMessage] = useState("");
  const status = String(task.status);
  const label = actionLabel(status);
  const placeholder = placeholderFor(status);

  async function submit() {
    if (!message.trim() || busy) return;
    await onCorrection(message.trim());
    setMessage("");
  }

  return (
    <section className="panel">
      <h2>Status action</h2>
      <p className="approval-note">{label}</p>
      <textarea
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={(event) => {
          if (event.ctrlKey && event.key === "Enter") {
            void submit();
          }
        }}
        placeholder={placeholder}
        rows={5}
      />
      <button type="button" disabled={!message.trim() || busy === "correction"} onClick={() => void submit()}>
        <Send size={16} />
        {busy === "correction" ? "Queueing..." : buttonLabel(status)}
      </button>
    </section>
  );
}

function actionLabel(status: string) {
  if (status === "changes_requested") return "Create a correction plan from the requested changes.";
  if (status === "validation_failed") return "Send validation notes and generate a focused repair plan.";
  if (status === "prompt_too_large") return "Ask Tasker to compact context before retrying execution.";
  if (status === "plan_rejected") return "Revise the rejected plan with a concrete correction request.";
  return "Send a task message or correction request.";
}

function placeholderFor(status: string) {
  if (status === "prompt_too_large") return "Compact context and retry execution with only the latest approved artifacts.";
  if (status === "changes_requested") return "Create correction plan from my comments: ...";
  if (status === "validation_failed") return "Repair validation failure: ...";
  return "Message to task / correction request";
}

function buttonLabel(status: string) {
  if (status === "changes_requested") return "Create correction plan";
  if (status === "validation_failed") return "Retry with repair plan";
  if (status === "prompt_too_large") return "Compact context";
  return "Send message";
}
