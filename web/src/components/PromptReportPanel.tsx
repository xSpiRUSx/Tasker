import { useEffect, useMemo, useState } from "react";
import { listModelCalls, listPromptBuilds } from "../api/client";
import type { ModelCall, PromptBuild } from "../api/types";

interface PromptReportPanelProps {
  setError: (message: string | null) => void;
  taskId: string;
}

interface ModelTokenSummary {
  calls: number;
  cachedPromptTokens: number;
  completionTokens: number;
  costUsd: number;
  estimatedCalls: number;
  model: string;
  promptTokens: number;
  provider: string;
  reasoningTokens: number;
  runtime: string;
  sources: Set<string>;
  totalTokens: number;
}

export function PromptReportPanel({ setError, taskId }: PromptReportPanelProps) {
  const [modelCalls, setModelCalls] = useState<ModelCall[]>([]);
  const [promptBuilds, setPromptBuilds] = useState<PromptBuild[]>([]);

  useEffect(() => {
    async function load() {
      try {
        const [callsResponse, promptsResponse] = await Promise.all([
          listModelCalls(taskId),
          listPromptBuilds(taskId),
        ]);
        setModelCalls(callsResponse.items);
        setPromptBuilds(promptsResponse.items.slice().reverse());
      } catch (error) {
        setError(error instanceof Error ? error.message : "Failed to load token report");
      }
    }
    void load();
  }, [setError, taskId]);

  const byModel = useMemo(() => summarizeByModel(modelCalls), [modelCalls]);
  const latestPrompt = promptBuilds[0];
  const hasCost = byModel.some((item) => item.costUsd > 0);
  const grandTotal = byModel.reduce((sum, item) => sum + item.totalTokens, 0);
  const hasEstimatedCalls = modelCalls.some((item) => item.usage_is_estimated);
  const hasCachedTokens = modelCalls.some((item) => item.cached_prompt_tokens != null);
  const hasReasoningTokens = modelCalls.some((item) => item.reasoning_tokens != null);
  const hasTotalOnlyCalls = modelCalls.some((item) => item.total_tokens != null && item.prompt_tokens == null && item.completion_tokens == null);

  return (
    <section className="panel">
      <h2>Tokens</h2>
      {byModel.length ? (
        <>
          <div className="token-summary">
            <div>
              <span>Total</span>
              <strong>{formatInteger(grandTotal)}</strong>
            </div>
            <div>
              <span>Calls</span>
              <strong>{formatInteger(modelCalls.length)}</strong>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Input</th>
                  {hasCachedTokens ? <th>Cached</th> : null}
                  <th>Output</th>
                  {hasReasoningTokens ? <th>Reasoning</th> : null}
                  <th>Total</th>
                  <th>Source</th>
                  {hasCost ? <th>Cost</th> : null}
                </tr>
              </thead>
              <tbody>
                {byModel.map((item) => (
                  <tr key={`${item.runtime}:${item.provider}:${item.model}`}>
                    <td>
                      <strong>{item.model}</strong>
                      <small>
                        {item.runtime} / {item.provider || "provider unknown"} / {item.calls} calls
                      </small>
                    </td>
                    <td>{formatKnownInteger(item.promptTokens, hasPromptBreakdown(modelCalls, item))}</td>
                    {hasCachedTokens ? <td>{formatInteger(item.cachedPromptTokens)}</td> : null}
                    <td>{formatKnownInteger(item.completionTokens, hasCompletionBreakdown(modelCalls, item))}</td>
                    {hasReasoningTokens ? <td>{formatInteger(item.reasoningTokens)}</td> : null}
                    <td>{formatInteger(item.totalTokens)}</td>
                    <td>{formatSources(item)}</td>
                    {hasCost ? <td>{formatCost(item.costUsd)}</td> : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {hasEstimatedCalls || hasTotalOnlyCalls ? (
            <p className="approval-note">
              {hasTotalOnlyCalls
                ? "Some Codex CLI calls report only total tokens; input/output/cache split is unavailable for those rows."
                : "Some token rows are character-based estimates because the runtime did not report token usage."}
            </p>
          ) : null}
          <h3>Latest Calls</h3>
          <div className="timeline">
            {modelCalls.slice(-4).reverse().map((item) => (
              <div className="timeline-item" key={item.id}>
                <strong>{item.operation}</strong>
                <dl className="kv">
                  <dt>Model</dt>
                  <dd>{item.model}</dd>
                  <dt>Runtime</dt>
                  <dd>{item.runtime}</dd>
                  <dt>Tokens</dt>
                  <dd>{formatInteger(callTotal(item))}</dd>
                  <dt>Usage source</dt>
                  <dd>{item.usage_source || "unknown"}</dd>
                  <dt>Status</dt>
                  <dd>{item.status || "unknown"}</dd>
                </dl>
              </div>
            ))}
          </div>
        </>
      ) : latestPrompt ? (
        <>
          <div className="empty">No recorded model calls yet.</div>
          <h3>Latest Prompt Build</h3>
          <dl className="kv">
            <dt>Operation</dt>
            <dd>{latestPrompt.operation}</dd>
            <dt>Status</dt>
            <dd>{latestPrompt.status}</dd>
            <dt>Prompt chars</dt>
            <dd>{latestPrompt.total_chars.toLocaleString()}</dd>
            <dt>Budget</dt>
            <dd>{latestPrompt.budget_chars.toLocaleString()}</dd>
            <dt>Included</dt>
            <dd>{latestPrompt.included.length}</dd>
            <dt>Excluded</dt>
            <dd>{latestPrompt.excluded.length}</dd>
          </dl>
        </>
      ) : (
        <div className="empty">No token reports yet.</div>
      )}
    </section>
  );
}

function summarizeByModel(items: ModelCall[]): ModelTokenSummary[] {
  const grouped = new Map<string, ModelTokenSummary>();
  items.forEach((item) => {
    const key = `${item.runtime}:${item.provider || ""}:${item.model}`;
    const current = grouped.get(key) || {
      calls: 0,
      cachedPromptTokens: 0,
      completionTokens: 0,
      costUsd: 0,
      estimatedCalls: 0,
      model: item.model,
      promptTokens: 0,
      provider: item.provider || "",
      reasoningTokens: 0,
      runtime: item.runtime,
      sources: new Set<string>(),
      totalTokens: 0,
    };
    current.calls += 1;
    current.promptTokens += item.prompt_tokens || 0;
    current.cachedPromptTokens += item.cached_prompt_tokens || 0;
    current.completionTokens += item.completion_tokens || 0;
    current.reasoningTokens += item.reasoning_tokens || 0;
    current.totalTokens += callTotal(item);
    current.costUsd += item.cost_usd || 0;
    current.estimatedCalls += item.usage_is_estimated ? 1 : 0;
    current.sources.add(item.usage_source || "unknown");
    grouped.set(key, current);
  });
  return Array.from(grouped.values()).sort((left, right) => right.totalTokens - left.totalTokens);
}

function callTotal(item: ModelCall): number {
  return item.total_tokens ?? (item.prompt_tokens || 0) + (item.completion_tokens || 0);
}

function hasPromptBreakdown(items: ModelCall[], summary: ModelTokenSummary): boolean {
  return items.some((item) => isSameSummary(item, summary) && item.prompt_tokens != null);
}

function hasCompletionBreakdown(items: ModelCall[], summary: ModelTokenSummary): boolean {
  return items.some((item) => isSameSummary(item, summary) && item.completion_tokens != null);
}

function isSameSummary(item: ModelCall, summary: ModelTokenSummary): boolean {
  return item.runtime === summary.runtime && (item.provider || "") === summary.provider && item.model === summary.model;
}

function formatKnownInteger(value: number, isKnown: boolean): string {
  return isKnown ? formatInteger(value) : "n/a";
}

function formatInteger(value: number): string {
  return value.toLocaleString();
}

function formatCost(value: number): string {
  if (!value) {
    return "-";
  }
  return `$${value.toFixed(4)}`;
}

function formatSources(item: ModelTokenSummary): string {
  const sources = Array.from(item.sources).join(", ");
  if (!item.estimatedCalls) {
    return sources;
  }
  return `${sources} (${item.estimatedCalls} est.)`;
}
