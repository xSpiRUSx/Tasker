import { useEffect, useState } from "react";
import { listPromptBuilds } from "../api/client";
import type { PromptBuild } from "../api/types";

interface PromptReportPanelProps {
  setError: (message: string | null) => void;
  taskId: string;
}

export function PromptReportPanel({ setError, taskId }: PromptReportPanelProps) {
  const [items, setItems] = useState<PromptBuild[]>([]);

  useEffect(() => {
    async function load() {
      try {
        const response = await listPromptBuilds(taskId);
        setItems(response.items.slice().reverse());
      } catch (error) {
        setError(error instanceof Error ? error.message : "Не удалось загрузить отчет токенов");
      }
    }
    void load();
  }, [setError, taskId]);

  const latest = items[0];

  return (
    <section className="panel">
      <h2>Токены</h2>
      {latest ? (
        <>
          <dl className="kv">
            <dt>Операция</dt>
            <dd>{latest.operation}</dd>
            <dt>Статус</dt>
            <dd>{latest.status}</dd>
            <dt>Символы prompt</dt>
            <dd>{latest.total_chars.toLocaleString()}</dd>
            <dt>Бюджет</dt>
            <dd>{latest.budget_chars.toLocaleString()}</dd>
            <dt>Включено</dt>
            <dd>{latest.included.length}</dd>
            <dt>Исключено</dt>
            <dd>{latest.excluded.length}</dd>
          </dl>
        </>
      ) : (
        <div className="empty">Отчетов prompt пока нет.</div>
      )}
    </section>
  );
}
