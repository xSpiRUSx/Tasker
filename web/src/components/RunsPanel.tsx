import { useEffect, useState } from "react";
import { listRuns, listRunSteps } from "../api/client";
import type { AgentRun, AgentStep } from "../api/types";
import { displayValue, formatDate, statusLabel } from "../i18n";

interface RunsPanelProps {
  setError: (message: string | null) => void;
  taskId: string;
}

export function RunsPanel({ setError, taskId }: RunsPanelProps) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [steps, setSteps] = useState<Record<string, AgentStep[]>>({});
  const [available, setAvailable] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const response = await listRuns(taskId);
        setRuns(response.items);
        setAvailable(response.available);
        const stepPairs = await Promise.all(response.items.map(async (run) => [run.id, await listRunSteps(run.id)] as const));
        setSteps(Object.fromEntries(stepPairs));
        setError(null);
      } catch (error) {
        setError(error instanceof Error ? error.message : "Не удалось загрузить запуски");
      }
    }
    void load();
  }, [setError, taskId]);

  if (!available) {
    return <section className="panel empty">Запуски пока недоступны. LoopEngine не включен.</section>;
  }

  return (
    <section className="panel">
      <h2>Запуски</h2>
      {runs.length === 0 ? <div className="empty">Запусков пока нет.</div> : null}
      {runs.map((run) => (
        <article className="run-card" key={run.id}>
          <h3>{run.id}</h3>
          <dl className="kv">
            <dt>type</dt>
            <dd>{run.run_type}</dd>
            <dt>status</dt>
            <dd>{statusLabel(run.status)}</dd>
            <dt>executor</dt>
            <dd>{displayValue(run.executor)}</dd>
            <dt>started</dt>
            <dd>{formatDate(run.started_at)}</dd>
            <dt>finished</dt>
            <dd>{formatDate(run.finished_at)}</dd>
          </dl>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>шаг</th>
                  <th>статус</th>
                  <th>итог</th>
                </tr>
              </thead>
              <tbody>
                {(steps[run.id] || []).map((step) => (
                  <tr key={step.id}>
                    <td>{step.step_index}</td>
                    <td>{step.step_type}</td>
                    <td>{step.status}</td>
                    <td>{step.output_summary || step.input_summary || step.error || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ))}
    </section>
  );
}
