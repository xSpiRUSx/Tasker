import { X } from "lucide-react";

interface ErrorBannerProps {
  message: string;
  onDismiss: () => void;
}

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  return (
    <div className="error-banner">
      <span>{message}</span>
      <button className="icon-button" type="button" onClick={onDismiss} aria-label="Закрыть ошибку" title="Закрыть ошибку">
        <X size={16} />
      </button>
    </div>
  );
}
