import { useEffect, useMemo, useState } from "react";
import { listEvents } from "../api/client";
import type { TaskEvent } from "../api/types";

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
        setError(error instanceof Error ? error.message : "Loading events failed");
      }
    }
    void load();
  }, [setError, taskId]);

  const visibleEvents = useMemo(() => (chronological ? events : [...events].reverse()), [chronological, events]);

  return (
    <section className="panel">
      <div className="section-title">
        <h2>Events</h2>
        <label className="toggle">
          <input checked={chronological} onChange={(event) => setChronological(event.target.checked)} type="checkbox" />
          chronological
        </label>
      </div>
      <div className="timeline">
        {visibleEvents.map((event) => (
          <article className="timeline-item" key={event.id}>
            <time>{new Date(event.created_at).toLocaleString()}</time>
            <strong>{event.event_type}</strong>
            <pre className="json-block">{JSON.stringify(event.payload, null, 2)}</pre>
          </article>
        ))}
      </div>
    </section>
  );
}
