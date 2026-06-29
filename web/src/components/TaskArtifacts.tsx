import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { listArtifacts, readArtifactById } from "../api/client";
import type { ArtifactContentResponse, TaskArtifact } from "../api/types";
import { formatDate } from "../i18n";
import { ArtifactViewer } from "./ArtifactViewer";

interface TaskArtifactsProps {
  setError: (message: string | null) => void;
  taskId: string;
}

const KIND_ORDER = [
  "task_index",
  "route_decision",
  "context_summary",
  "working_memory",
  "spec",
  "todo",
  "test_plan",
  "approval_request",
  "execution_log",
  "validation_report",
  "evaluation_report",
  "review_report",
  "diff_summary",
  "diff_patch",
  "commit_message",
  "commit_result",
  "deploy_plan",
  "rollback_plan",
  "final_report",
  "events",
];

export function TaskArtifacts({ setError, taskId }: TaskArtifactsProps) {
  const [artifacts, setArtifacts] = useState<TaskArtifact[]>([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [content, setContent] = useState<ArtifactContentResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const sortedArtifacts = useMemo(() => {
    return [...artifacts].sort((a, b) => {
      const orderA = KIND_ORDER.indexOf(a.kind);
      const orderB = KIND_ORDER.indexOf(b.kind);
      const safeA = orderA === -1 ? 999 : orderA;
      const safeB = orderB === -1 ? 999 : orderB;
      return safeA - safeB || a.kind.localeCompare(b.kind) || (a.version || 0) - (b.version || 0);
    });
  }, [artifacts]);

  const loadArtifacts = useCallback(async () => {
    setLoading(true);
    try {
      const response = await listArtifacts(taskId);
      setArtifacts(response.items);
      setSelectedArtifactId((current) => current || response.items[0]?.id || null);
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось загрузить артефакты");
    } finally {
      setLoading(false);
    }
  }, [setError, taskId]);

  const loadContent = useCallback(async () => {
    if (!selectedArtifactId) {
      setContent(null);
      return;
    }
    try {
      setContent(await readArtifactById(taskId, selectedArtifactId));
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось загрузить артефакт");
    }
  }, [selectedArtifactId, setError, taskId]);

  useEffect(() => {
    void loadArtifacts();
  }, [loadArtifacts]);

  useEffect(() => {
    if (selectedArtifactId && !artifacts.some((artifact) => artifact.id === selectedArtifactId)) {
      setSelectedArtifactId(artifacts[0]?.id || null);
    }
  }, [artifacts, selectedArtifactId]);

  useEffect(() => {
    void loadContent();
  }, [loadContent]);

  return (
    <section className="artifact-tab">
      <div className="artifact-list panel">
        <div className="section-title">
          <h2>Артефакты</h2>
          <button className="icon-button" type="button" onClick={() => void loadArtifacts()} title="Обновить артефакты">
            <RefreshCw size={16} />
          </button>
        </div>
        {loading ? <div className="empty">Загружаю артефакты...</div> : null}
        {sortedArtifacts.map((artifact) => (
          <button
            className={artifact.id === selectedArtifactId ? "artifact-item artifact-item--selected" : "artifact-item"}
            key={artifact.id}
            type="button"
            onClick={() => setSelectedArtifactId(artifact.id)}
          >
            <strong>{artifact.title}</strong>
            <span>
              {artifact.kind}
              {artifact.version ? ` v${artifact.version}` : ""}
            </span>
            <small>{artifact.relative_path}</small>
            <small>{formatDate(artifact.updated_at)}</small>
          </button>
        ))}
      </div>
      <ArtifactViewer content={content} onRefresh={() => void loadContent()} />
    </section>
  );
}
