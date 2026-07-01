import { useState } from "react";
import { ChevronDown, Eye, Plus } from "lucide-react";
import type { RouteDecision } from "../api/types";
import { complexityLabel, displayValue, gateLabel, riskLabel } from "../i18n";

interface TaskCreateFormProps {
  advancedUi: boolean;
  busy: string | null;
  layout?: "compact" | "page";
  onCreate: (input: { message: string; source?: string | null; user_id?: string | null }) => Promise<void>;
  onPreview: (message: string) => Promise<void>;
  routePreview: RouteDecision | null;
}

export function TaskCreateForm({ advancedUi, busy, layout = "compact", onCreate, onPreview, routePreview }: TaskCreateFormProps) {
  const [message, setMessage] = useState("");
  const [source, setSource] = useState("web");
  const [userId, setUserId] = useState("");
  const [showRouteTools, setShowRouteTools] = useState(false);

  const canSubmit = message.trim().length > 0 && !busy;
  const routeToolsVisible = advancedUi || showRouteTools;

  async function submit() {
    if (!canSubmit) return;
    await onCreate({ message: message.trim(), source: source.trim() || "web", user_id: userId.trim() || null });
    setMessage("");
  }

  return (
    <section className={layout === "page" ? "panel new-task new-task--page" : "panel new-task"}>
      <div className="new-task__intro">
        <h2>Создать задачу</h2>
        <p>Опишите задачу обычным языком. Tasker сам выберет подходящий сценарий, подготовит артефакты и покажет действия, которые нужно подтвердить.</p>
      </div>
      <label className="field-label">
        <span>Что нужно сделать?</span>
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if (event.ctrlKey && event.key === "Enter") {
              void submit();
            }
          }}
          placeholder="Например: проверь проект, найди ошибку в авторизации и предложи исправление"
          rows={layout === "page" ? 9 : 5}
        />
      </label>
      <p className="form-hint">После создания задачи вы увидите план, артефакты и действия, которые нужно подтвердить. Ctrl+Enter тоже создает задачу.</p>

      {advancedUi ? (
        <div className="field-grid">
          <label className="field-label">
            <span>Источник</span>
            <input value={source} onChange={(event) => setSource(event.target.value)} placeholder="web" />
          </label>
          <label className="field-label">
            <span>Пользователь</span>
            <input value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="не задан" />
          </label>
        </div>
      ) : null}

      {!advancedUi ? (
        <button className="ghost-button" type="button" onClick={() => setShowRouteTools((value) => !value)}>
          <ChevronDown size={16} />
          Показать, как будет обработана задача
        </button>
      ) : null}

      <div className="button-row">
        {routeToolsVisible ? (
          <button type="button" disabled={!canSubmit || busy === "preview"} onClick={() => void onPreview(message.trim())}>
            <Eye size={16} />
            {busy === "preview" ? "Проверяю маршрут..." : "Проверить маршрут"}
          </button>
        ) : null}
        <button type="button" disabled={!canSubmit || busy === "create"} onClick={() => void submit()}>
          <Plus size={16} />
          {busy === "create" ? "Создаю..." : "Создать задачу"}
        </button>
      </div>

      {routePreview && routeToolsVisible ? (
        <div className="route-preview">
          <h3>Как будет обработана задача</h3>
          <dl>
            <Row label="Проект" value={routePreview.project_name || (routePreview.project_id ? "проект выбран" : null)} />
            <Row label="Сценарий работы" value={routePreview.workflow_name || (routePreview.workflow_id ? "сценарий выбран" : null)} />
            <Row label="Тип задачи" value={routePreview.task_kind} />
            <Row label="Сложность" value={complexityLabel(routePreview.complexity)} />
            <Row label="Риск" value={riskLabel(routePreview.risk_level)} />
            <Row label="Что потребуется подтвердить" value={(routePreview.approval_gates || []).map((gate) => gateLabel(gate)).join(", ")} />
            <Row label="Замечания" value={(routePreview.warnings || []).join(", ")} />
            <Row label="Почему выбран такой маршрут" value={routePreview.rationale} />
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
      <dd>{displayValue(typeof value === "string" ? value : value ? String(value) : null)}</dd>
    </>
  );
}
