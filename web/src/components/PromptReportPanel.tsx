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
        setError(error instanceof Error ? error.message : "Prompt report load failed");
      }
    }
    void load();
  }, [setError, taskId]);

  const latest = items[0];

  return (
    <section className="panel">
      <h2>Token report</h2>
      {latest ? (
        <>
          <dl className="kv">
            <dt>Operation</dt>
            <dd>{latest.operation}</dd>
            <dt>Status</dt>
            <dd>{latest.status}</dd>
            <dt>Prompt chars</dt>
            <dd>{latest.total_chars.toLocaleString()}</dd>
            <dt>Budget chars</dt>
            <dd>{latest.budget_chars.toLocaleString()}</dd>
            <dt>Included</dt>
            <dd>{latest.included.length}</dd>
            <dt>Excluded</dt>
            <dd>{latest.excluded.length}</dd>
          </dl>
        </>
      ) : (
        <div className="empty">No prompt builds recorded.</div>
      )}
    </section>
  );
}
