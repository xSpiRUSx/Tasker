import type {
  AgentRun,
  AgentStep,
  Approval,
  ApprovalDecisionInput,
  ArtifactContentResponse,
  CreateTaskRequest,
  CreateTaskResponse,
  HealthResponse,
  JobAcceptedResponse,
  ListTasksParams,
  ListTasksResponse,
  RouteDecision,
  Task,
  TaskArtifact,
  TaskEvent,
  TaskJob,
} from "./types";

const API_BASE = (import.meta.env.VITE_TASKER_API_BASE || "http://127.0.0.1:8000").replace(/\/$/, "");

export class ApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (error) {
    throw new ApiError(error instanceof Error ? error.message : "Network request failed");
  }

  const text = await response.text();
  const payload = text ? safeJson(text) : null;

  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload ? String(payload.detail) : text;
    throw new ApiError(`HTTP ${response.status}: ${detail || response.statusText}`, response.status);
  }

  return payload as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function params(input: { [key: string]: string | number | undefined }): string {
  const query = new URLSearchParams();
  Object.entries(input).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      query.set(key, String(value));
    }
  });
  const value = query.toString();
  return value ? `?${value}` : "";
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function routeTask(message: string): Promise<RouteDecision> {
  return request<RouteDecision>("/route", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export async function listTasks(input: ListTasksParams = {}): Promise<ListTasksResponse> {
  const payload = await request<ListTasksResponse | Task[]>("/tasks" + params({ ...input }));
  if (Array.isArray(payload)) {
    return { items: payload, total: payload.length, limit: input.limit ?? payload.length, offset: input.offset ?? 0 };
  }
  return payload;
}

export function createTask(input: CreateTaskRequest): Promise<CreateTaskResponse> {
  return request<CreateTaskResponse>("/tasks", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getTask(taskId: string): Promise<Task> {
  return request<Task>(`/tasks/${encodeURIComponent(taskId)}`);
}

export async function listArtifacts(taskId: string): Promise<{ items: TaskArtifact[] }> {
  const payload = await request<{ items: TaskArtifact[] } | TaskArtifact[]>(`/tasks/${encodeURIComponent(taskId)}/artifacts`);
  return Array.isArray(payload) ? { items: payload } : payload;
}

export function readArtifactById(taskId: string, artifactId: string): Promise<ArtifactContentResponse> {
  return request<ArtifactContentResponse>(
    `/tasks/${encodeURIComponent(taskId)}/artifacts/by-id/${encodeURIComponent(artifactId)}`,
  );
}

export async function listApprovals(taskId: string): Promise<{ items: Approval[] }> {
  const payload = await request<{ items: Approval[] } | Approval[]>(`/tasks/${encodeURIComponent(taskId)}/approvals`);
  return Array.isArray(payload) ? { items: payload } : payload;
}

export async function listEvents(taskId: string): Promise<{ items: TaskEvent[] }> {
  const payload = await request<{ items: TaskEvent[] } | TaskEvent[]>(`/tasks/${encodeURIComponent(taskId)}/events`);
  return Array.isArray(payload) ? { items: payload } : payload;
}

export function decideApproval(taskId: string, gate: string, input: ApprovalDecisionInput): Promise<JobAcceptedResponse> {
  return request<JobAcceptedResponse>(`/tasks/${encodeURIComponent(taskId)}/approvals/${encodeURIComponent(gate)}`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function sendTaskMessage(taskId: string, message: string): Promise<JobAcceptedResponse> {
  return request<JobAcceptedResponse>(`/tasks/${encodeURIComponent(taskId)}/messages`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export async function listJobs(taskId: string): Promise<{ items: TaskJob[] }> {
  const payload = await request<{ items: TaskJob[] } | TaskJob[]>(`/tasks/${encodeURIComponent(taskId)}/jobs`);
  return Array.isArray(payload) ? { items: payload } : payload;
}

export function cancelTask(taskId: string, comment?: string): Promise<Task> {
  return request<Task>(`/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: "POST",
    body: JSON.stringify({ comment }),
  });
}

export async function listRuns(taskId: string): Promise<{ items: AgentRun[]; available: boolean }> {
  try {
    const payload = await request<{ items: AgentRun[] } | AgentRun[]>(`/tasks/${encodeURIComponent(taskId)}/runs`);
    return { items: Array.isArray(payload) ? payload : payload.items, available: true };
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 501)) {
      return { items: [], available: false };
    }
    throw error;
  }
}

export async function listRunSteps(runId: string): Promise<AgentStep[]> {
  const payload = await request<{ items: AgentStep[] } | AgentStep[]>(`/runs/${encodeURIComponent(runId)}/steps`);
  return Array.isArray(payload) ? payload : payload.items;
}
