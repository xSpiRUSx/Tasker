import type { ReactNode } from "react";
import { Activity, AlertCircle, CheckCircle2, FileSliders, ListTodo, PlusCircle, Route, Settings } from "lucide-react";
import { ErrorBanner } from "./ErrorBanner";

export type AppView = "create" | "tasks" | "settings" | "config" | "routing";

interface AppShellProps {
  advancedUi: boolean;
  apiHealthy: boolean;
  children: ReactNode;
  currentView: AppView;
  error: string | null;
  layoutMode: "single" | "split";
  toast: string | null;
  onDismissError: () => void;
  onNavigate: (view: AppView) => void;
}

const NAV_ITEMS: Array<{ advancedOnly?: boolean; view: AppView; href: string; label: string; icon: ReactNode }> = [
  { view: "create", href: "/tasks/new", label: "Создать задачу", icon: <PlusCircle size={16} /> },
  { view: "tasks", href: "/tasks", label: "Задачи", icon: <ListTodo size={16} /> },
  { view: "settings", href: "/settings", label: "Настройки", icon: <Settings size={16} /> },
  { advancedOnly: true, view: "config", href: "/settings/config", label: "Конфигурация", icon: <FileSliders size={16} /> },
  { advancedOnly: true, view: "routing", href: "/settings/routing-rules", label: "Маршрутизация", icon: <Route size={16} /> },
];

export function AppShell({
  advancedUi,
  apiHealthy,
  children,
  currentView,
  error,
  layoutMode,
  toast,
  onDismissError,
  onNavigate,
}: AppShellProps) {
  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__left">
          <a className="brand" href="/">
            Tasker
          </a>
          <nav className="topbar__nav" aria-label="Основная навигация">
            {NAV_ITEMS.filter((item) => advancedUi || !item.advancedOnly).map((item) => (
              <a
                className={currentView === item.view ? "topbar__link topbar__link--active" : "topbar__link"}
                href={item.href}
                key={item.view}
                onClick={(event) => {
                  event.preventDefault();
                  onNavigate(item.view);
                }}
              >
                {item.icon}
                {item.label}
              </a>
            ))}
          </nav>
        </div>
        <div
          className={apiHealthy ? "api-state api-state--ok" : "api-state api-state--bad"}
          title={apiHealthy ? "Сервер отвечает на запросы" : "Проверьте, запущен ли backend Tasker"}
        >
          {apiHealthy ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
          {apiHealthy ? "Сервер подключен" : "Нет связи с сервером"}
        </div>
      </header>
      {error ? <ErrorBanner message={error} onDismiss={onDismissError} /> : null}
      {toast ? (
        <div className="toast">
          <Activity size={16} />
          {toast}
        </div>
      ) : null}
      <div className={layoutMode === "single" ? "layout layout--single" : "layout"}>{children}</div>
    </div>
  );
}
