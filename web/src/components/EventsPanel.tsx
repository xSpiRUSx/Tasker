import { useEffect, useMemo, useState } from "react";
import { listEvents } from "../api/client";
import type { TaskEvent } from "../api/types";
import { formatDate } from "../i18n";

interface EventsPanelProps {
  setError: (message: string | null) => void;
  taskId: string;
}

export function EventsPanel({ setError, taskId }: EventsPanelProps) {
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [chronological, setChronological] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const response = await listEvents(taskId);
        setEvents(response.items);
        setError(null);
      } catch (error) {
        setError(error instanceof Error ? error.message : "Не удалось загрузить события");
      }
    }
    void load();
  }, [setError, taskId]);

  const visibleEvents = useMemo(() => (chronological ? events : [...events].reverse()), [chronological, events]);

  return (
    <section className="panel">
      <div className="section-title">
        <h2>События</h2>
        <label className="toggle">
          <input checked={chronological} onChange={(event) => setChronological(event.target.checked)} type="checkbox" />
          хронологически
        </label>
      </div>
      <div className="timeline">
        {visibleEvents.map((event) => (
          <article className="timeline-item" key={event.id}>
            <time>{formatDate(event.created_at)}</time>
            <strong>{event.event_type}</strong>
            <pre className="json-block">{JSON.stringify(event.payload, null, 2)}</pre>
          </article>
        ))}
      </div>
    </section>
  );
}
