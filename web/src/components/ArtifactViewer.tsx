import { Copy, RefreshCw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { ArtifactContentResponse } from "../api/types";

interface ArtifactViewerProps {
  content: ArtifactContentResponse | null;
  onRefresh: () => void;
}

export function ArtifactViewer({ content, onRefresh }: ArtifactViewerProps) {
  if (!content) {
    return (
      <section className="artifact-viewer panel">
        <div className="empty">Выберите артефакт.</div>
      </section>
    );
  }

  const isMarkdown = content.artifact.content_type === "text/markdown";
  const isPatch = content.artifact.kind === "diff_patch";

  return (
    <section className="artifact-viewer panel">
      <div className="artifact-viewer__header">
        <div>
          <h2>{content.artifact.title}</h2>
          <span>{content.artifact.relative_path}</span>
        </div>
        <div className="button-row">
          <button type="button" onClick={() => void navigator.clipboard.writeText(content.content)}>
            <Copy size={16} />
            Скопировать
          </button>
          <button type="button" onClick={() => void navigator.clipboard.writeText(content.artifact.relative_path)}>
            <Copy size={16} />
            Путь
          </button>
          <button type="button" onClick={onRefresh}>
            <RefreshCw size={16} />
            Обновить
          </button>
        </div>
      </div>
      {isPatch || !isMarkdown ? (
        <pre className="artifact-pre">
          <code>{content.content}</code>
        </pre>
      ) : (
        <div className="markdown">
          <ReactMarkdown skipHtml>{content.content}</ReactMarkdown>
        </div>
      )}
    </section>
  );
}
