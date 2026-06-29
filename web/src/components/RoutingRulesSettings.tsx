import { Check, CircleSlash, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  disableRoutingRule,
  listRoutingRules,
  listRoutingSuggestions,
  promoteRoutingRule,
  promoteRoutingSuggestion,
  rejectRoutingRule,
  rejectRoutingSuggestion,
} from "../api/client";
import type { RoutingRule, RoutingSuggestion } from "../api/types";
import { StatusBadge } from "./StatusBadge";

interface RoutingRulesSettingsProps {
  setError: (value: string | null) => void;
  setToast: (value: string | null) => void;
}

export function RoutingRulesSettings({ setError, setToast }: RoutingRulesSettingsProps) {
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [suggestions, setSuggestions] = useState<RoutingSuggestion[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [ruleResponse, suggestionResponse] = await Promise.all([listRoutingRules(), listRoutingSuggestions()]);
    setRules(ruleResponse.items);
    setSuggestions(suggestionResponse.items);
  }, []);

  useEffect(() => {
    load().catch((error) => setError(error instanceof Error ? error.message : "Не удалось загрузить правила маршрутизации"));
  }, [load, setError]);

  const counts = useMemo(() => {
    return rules.reduce<Record<string, number>>((acc, rule) => {
      acc[rule.status] = (acc[rule.status] || 0) + 1;
      return acc;
    }, {});
  }, [rules]);

  async function runAction(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    try {
      await action();
      await load();
      setToast(label);
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : `${label}: ошибка`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="main settings-main">
      <section className="task-header">
        <div>
          <div className="task-header__title">
            <h1>Маршрутизация</h1>
          </div>
          <dl className="task-header__meta">
            <dt>Активные</dt>
            <dd>{counts.active || 0}</dd>
            <dt>Ожидают</dt>
            <dd>{counts.pending || 0}</dd>
            <dt>Отклонены</dt>
            <dd>{counts.rejected || 0}</dd>
            <dt>Отключены</dt>
            <dd>{counts.disabled || 0}</dd>
          </dl>
        </div>
        <div className="task-header__actions">
          <button className="icon-button" onClick={() => void runAction("Правила обновлены", load)} disabled={busy !== null}>
            <RefreshCw size={16} />
          </button>
        </div>
      </section>

      <div className="settings-grid">
        <section className="panel">
          <div className="section-title">
            <h2>Предложения</h2>
            <StatusBadge status={`${suggestions.filter((item) => item.status === "pending").length} pending`} />
          </div>
          <div className="rule-list">
            {suggestions.length ? (
              suggestions.map((suggestion) => (
                <article className="rule-row" key={suggestion.id}>
                  <div className="rule-row__main">
                    <strong>{suggestion.id}</strong>
                    <span>{suggestion.message}</span>
                    <small>{suggestedRuleSummary(suggestion)}</small>
                  </div>
                  <div className="rule-row__meta">
                    <StatusBadge status={suggestion.status} />
                    <div className="button-row">
                      <button
                        className="icon-button"
                        disabled={busy !== null || suggestion.status !== "pending"}
                        onClick={() => void runAction("Предложение принято", () => promoteRoutingSuggestion(suggestion.id))}
                      >
                        <Check size={16} />
                      </button>
                      <button
                        className="icon-button"
                        disabled={busy !== null || suggestion.status !== "pending"}
                        onClick={() => void runAction("Предложение отклонено", () => rejectRoutingSuggestion(suggestion.id))}
                      >
                        <X size={16} />
                      </button>
                    </div>
                  </div>
                </article>
              ))
            ) : (
              <p className="empty">Предложений нет.</p>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="section-title">
            <h2>Правила</h2>
            <StatusBadge status={`${rules.length} total`} />
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Паттерн</th>
                  <th>Цель</th>
                  <th>Статус</th>
                  <th>Срабатывания</th>
                  <th>Ошибки</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rules.length ? (
                  rules.map((rule) => (
                    <tr key={rule.id}>
                      <td>
                        <strong>{rule.pattern}</strong>
                        <small>{rule.pattern_type}</small>
                      </td>
                      <td>
                        {rule.target_route_type}
                        <small>{rule.target_workflow_id || "без workflow"}</small>
                      </td>
                      <td>
                        <StatusBadge status={rule.status} />
                      </td>
                      <td>{rule.hit_count}</td>
                      <td>{rule.false_positive_count}</td>
                      <td>
                        <div className="button-row">
                          <button
                            className="icon-button"
                            disabled={busy !== null || rule.status === "active"}
                            onClick={() => void runAction("Правило активно", () => promoteRoutingRule(rule.id))}
                          >
                            <Check size={16} />
                          </button>
                          <button
                            className="icon-button"
                            disabled={busy !== null || rule.status === "rejected"}
                            onClick={() => void runAction("Правило отклонено", () => rejectRoutingRule(rule.id))}
                          >
                            <X size={16} />
                          </button>
                          <button
                            className="icon-button"
                            disabled={busy !== null || rule.status === "disabled"}
                            onClick={() => void runAction("Правило отключено", () => disableRoutingRule(rule.id))}
                          >
                            <CircleSlash size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6}>Правил пока нет.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}

function suggestedRuleSummary(suggestion: RoutingSuggestion): string {
  const first = suggestion.suggested_rules[0] || {};
  const route = String(first.target_route_type || "unknown");
  const confidence = Number(first.confidence || 0);
  return `${route} · ${confidence ? confidence.toFixed(2) : "n/a"}`;
}
