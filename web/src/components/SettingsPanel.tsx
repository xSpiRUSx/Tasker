import { FileSliders, Route } from "lucide-react";
import type { AppView } from "./AppShell";

interface SettingsPanelProps {
  advancedUi: boolean;
  onAdvancedUiChange: (value: boolean) => void;
  onNavigate: (view: AppView) => void;
}

export function SettingsPanel({ advancedUi, onAdvancedUiChange, onNavigate }: SettingsPanelProps) {
  return (
    <main className="main settings-main">
      <section className="panel settings-panel">
        <h2>Настройки</h2>
        <label className="toggle settings-toggle">
          <input type="checkbox" checked={advancedUi} onChange={(event) => onAdvancedUiChange(event.target.checked)} />
          <span>Расширенный режим</span>
        </label>
        <p className="muted-text">
          В обычном режиме Tasker показывает только создание задач, список, результаты и подтверждения. Технические данные и администрирование
          доступны здесь после включения расширенного режима.
        </p>
      </section>
      {advancedUi ? (
        <section className="panel settings-panel">
          <h2>Администрирование</h2>
          <div className="settings-links">
            <button type="button" onClick={() => onNavigate("config")}>
              <FileSliders size={16} />
              Конфигурация
            </button>
            <button type="button" onClick={() => onNavigate("routing")}>
              <Route size={16} />
              Правила маршрутизации
            </button>
          </div>
        </section>
      ) : null}
    </main>
  );
}
