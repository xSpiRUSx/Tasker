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
      <h2>Сообщение</h2>
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
        {busy === "correction" ? "Ставлю в очередь..." : buttonLabel(status)}
      </button>
    </section>
  );
}

function actionLabel(status: string) {
  if (status === "changes_requested") return "Создать план правки из комментария.";
  if (status === "executing_correction" || status === "validating_correction") return "Запрошенные правки применяются.";
  if (status === "awaiting_correction_diff_approval") return "Проверьте обновленный diff после правки.";
  if (status === "correction_blocked") return "Правка заблокирована; сузьте запрос или создайте связанную задачу.";
  if (status === "validation_failed") return "Отправьте замечания валидации и создайте план исправления.";
  if (status === "prompt_too_large") return "Попросите Tasker сжать контекст перед повторным запуском.";
  if (status === "plan_rejected") return "Уточните отклоненный план конкретным запросом.";
  return "Отправить сообщение или запрос правки.";
}

function placeholderFor(status: string) {
  if (status === "prompt_too_large") return "Сжать контекст и повторить выполнение только с актуальными артефактами.";
  if (status === "changes_requested") return "Создать план правки по моим комментариям: ...";
  if (status === "correction_blocked") return "Сузить правку до проверенного diff: ...";
  if (status === "validation_failed") return "Исправить ошибку валидации: ...";
  return "Сообщение к задаче / запрос правки";
}

function buttonLabel(status: string) {
  if (status === "changes_requested") return "Создать план правки";
  if (status === "correction_blocked") return "Отправить правку";
  if (status === "validation_failed") return "Повторить с планом";
  if (status === "prompt_too_large") return "Сжать контекст";
  return "Отправить";
}
