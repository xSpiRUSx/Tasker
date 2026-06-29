import type { ReactNode } from "react";
import { Activity, AlertCircle, CheckCircle2, Settings } from "lucide-react";
import { ErrorBanner } from "./ErrorBanner";

interface AppShellProps {
  apiHealthy: boolean;
  children: ReactNode;
  error: string | null;
  toast: string | null;
  onDismissError: () => void;
}

export function AppShell({ apiHealthy, children, error, toast, onDismissError }: AppShellProps) {
  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__left">
          <a className="brand" href="/">
            TAsker
          </a>
          <a className="topbar__link" href="/settings/routing-rules">
            <Settings size={16} />
            Routing
          </a>
        </div>
        <div className={apiHealthy ? "api-state api-state--ok" : "api-state api-state--bad"}>
          {apiHealthy ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
          API: {apiHealthy ? "healthy" : "unavailable"}
        </div>
      </header>
      {error ? <ErrorBanner message={error} onDismiss={onDismissError} /> : null}
      {toast ? (
        <div className="toast">
          <Activity size={16} />
          {toast}
        </div>
      ) : null}
      <div className="layout">{children}</div>
    </div>
  );
}
