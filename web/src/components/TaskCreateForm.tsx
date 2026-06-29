import { useState } from "react";
import { Eye, Plus } from "lucide-react";
import type { RouteDecision } from "../api/types";

interface TaskCreateFormProps {
  busy: string | null;
  layout?: "compact" | "page";
  onCreate: (input: { message: string; source?: string | null; user_id?: string | null }) => Promise<void>;
  onPreview: (message: string) => Promise<void>;
  routePreview: RouteDecision | null;
}

export function TaskCreateForm({ busy, layout = "compact", onCreate, onPreview, routePreview }: TaskCreateFormProps) {
  const [message, setMessage] = useState("");
  const [source, setSource] = useState("web");
  const [userId, setUserId] = useState("");

  const canSubmit = message.trim().length > 0 && !busy;

  async function submit() {
    if (!canSubmit) return;
    await onCreate({ message: message.trim(), source: source.trim() || "web", user_id: userId.trim() || null });
    setMessage("");
  }

  return (
    <section className={layout === "page" ? "panel new-task new-task--page" : "panel new-task"}>
      <h2>Новая задача</h2>
      <textarea
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={(event) => {
          if (event.ctrlKey && event.key === "Enter") {
            void submit();
          }
        }}
        placeholder="Опишите задачу"
        rows={layout === "page" ? 9 : 5}
      />
      <div className="field-grid">
        <input value={source} onChange={(event) => setSource(event.target.value)} placeholder="Источник" />
        <input value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="Пользователь" />
      </div>
      <div className="button-row">
        <button type="button" disabled={!canSubmit || busy === "preview"} onClick={() => void onPreview(message.trim())}>
          <Eye size={16} />
          {busy === "preview" ? "Строю маршрут..." : "Проверить маршрут"}
        </button>
        <button type="button" disabled={!canSubmit || busy === "create"} onClick={() => void submit()}>
          <Plus size={16} />
          {busy === "create" ? "Создаю..." : "Создать задачу"}
        </button>
      </div>
      {routePreview ? (
        <div className="route-preview">
          <dl>
            <Row label="project_id" value={routePreview.project_id} />
            <Row label="workflow_id" value={routePreview.workflow_id} />
            <Row label="intent" value={routePreview.intent} />
            <Row label="task_kind" value={routePreview.task_kind} />
            <Row label="complexity" value={routePreview.complexity} />
            <Row label="risk_level" value={routePreview.risk_level} />
            <Row label="approval_gates" value={(routePreview.approval_gates || []).join(", ")} />
            <Row label="warnings" value={(routePreview.warnings || []).join(", ")} />
            <Row label="rationale" value={routePreview.rationale} />
          </dl>
        </div>
      ) : null}
    </section>
  );
}

function Row({ label, value }: { label: string; value: unknown }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{String(value || "нет")}</dd>
    </>
  );
}
