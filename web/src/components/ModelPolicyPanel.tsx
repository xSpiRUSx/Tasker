import { useEffect, useState } from "react";
import { listModelDecisions } from "../api/client";
import type { ModelDecision } from "../api/types";

interface ModelPolicyPanelProps {
  setError: (message: string | null) => void;
  taskId: string;
}

export function ModelPolicyPanel({ setError, taskId }: ModelPolicyPanelProps) {
  const [items, setItems] = useState<ModelDecision[]>([]);

  useEffect(() => {
    async function load() {
      try {
        const response = await listModelDecisions(taskId);
        setItems(response.items);
      } catch (error) {
        setError(error instanceof Error ? error.message : "Model decisions load failed");
      }
    }
    void load();
  }, [setError, taskId]);

  return (
    <section className="panel">
      <h2>Model policy</h2>
      {items.length ? (
        <div className="timeline">
          {items.slice(-5).map((item) => (
            <div className="timeline-item" key={item.id}>
              <strong>{item.operation}</strong>
              <dl className="kv">
                <dt>Target</dt>
                <dd>{item.selected_target}</dd>
                <dt>Runtime</dt>
                <dd>{item.runtime}</dd>
                <dt>Model</dt>
                <dd>{item.model}</dd>
                <dt>Reasoning</dt>
                <dd>{item.reasoning_effort || "none"}</dd>
                <dt>Reason</dt>
                <dd>{item.reason}</dd>
              </dl>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty">No model decisions recorded.</div>
      )}
    </section>
  );
}
