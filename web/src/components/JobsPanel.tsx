import { useEffect, useState } from "react";
import { Ban } from "lucide-react";
import { cancelJob, listJobs } from "../api/client";
import type { TaskJob } from "../api/types";
import { displayValue, formatDate, statusLabel } from "../i18n";

interface JobsPanelProps {
  setError: (message: string | null) => void;
  taskId: string;
}

export function JobsPanel({ setError, taskId }: JobsPanelProps) {
  const [jobs, setJobs] = useState<TaskJob[]>([]);

  async function load() {
    try {
      const response = await listJobs(taskId);
      setJobs(response.items.slice().reverse());
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось загрузить jobs");
    }
  }

  async function cancel(id: string) {
    try {
      await cancelJob(id);
      await load();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось отменить job");
    }
  }

  useEffect(() => {
    void load();
  }, [taskId]);

  const current = jobs.find((job) => job.status === "running" || job.status === "queued") || jobs[0];

  return (
    <section className="panel">
      <h2>Jobs</h2>
      {current ? (
        <dl className="kv">
          <dt>Действие</dt>
          <dd>{current.action}</dd>
          <dt>Статус</dt>
          <dd>{statusLabel(current.status)}</dd>
          <dt>Старт</dt>
          <dd>{formatDate(current.started_at)}</dd>
          <dt>Ошибка</dt>
          <dd>{displayValue(current.error)}</dd>
        </dl>
      ) : (
        <div className="empty">Jobs пока нет.</div>
      )}
      {current && ["queued", "running"].includes(String(current.status)) ? (
        <button className="icon-button" type="button" onClick={() => void cancel(current.id)}>
          <Ban size={16} />
          Отменить job
        </button>
      ) : null}
    </section>
  );
}
