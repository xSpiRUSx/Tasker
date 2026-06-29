import { useEffect, useState } from "react";
import { Ban } from "lucide-react";
import { cancelJob, listJobs } from "../api/client";
import type { TaskJob } from "../api/types";

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
      setError(error instanceof Error ? error.message : "Jobs load failed");
    }
  }

  async function cancel(id: string) {
    try {
      await cancelJob(id);
      await load();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Cancel job failed");
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
          <dt>Action</dt>
          <dd>{current.action}</dd>
          <dt>Status</dt>
          <dd>{current.status}</dd>
          <dt>Started</dt>
          <dd>{current.started_at ? new Date(current.started_at).toLocaleString() : "not started"}</dd>
          <dt>Error</dt>
          <dd>{current.error || "none"}</dd>
        </dl>
      ) : (
        <div className="empty">No jobs.</div>
      )}
      {current && ["queued", "running"].includes(String(current.status)) ? (
        <button className="icon-button" type="button" onClick={() => void cancel(current.id)}>
          <Ban size={16} />
          Cancel job
        </button>
      ) : null}
    </section>
  );
}
