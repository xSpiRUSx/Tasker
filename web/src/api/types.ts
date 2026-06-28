export type TaskStatus =
  | "created"
  | "routing"
  | "routed"
  | "awaiting_clarification"
  | "planning"
  | "awaiting_plan_approval"
  | "awaiting_spec_approval"
  | "awaiting_config_approval"
  | "awaiting_migration_approval"
  | "awaiting_security_approval"
  | "plan_rejected"
  | "approved_for_execution"
  | "preparing_worktree"
  | "executing"
  | "validating"
  | "reviewing"
  | "validation_failed"
  | "awaiting_diff_approval"
  | "changes_requested"
  | "awaiting_commit_approval"
  | "approved_for_commit"
  | "committing"
  | "deploy_prep"
  | "awaiting_deploy_approval"
  | "closed"
  | "failed"
  | "cancelled";

export interface HealthResponse {
  ok: boolean;
  app?: string;
}

export interface Task {
  id: string;
  status: TaskStatus | string;
  user_message: string;
  source?: string | null;
  user_id?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  project_path?: string | null;
  workflow_id?: string | null;
  workflow_name?: string | null;
  risk_level?: string | null;
  route_decision?: Record<string, unknown> | null;
  branch_name?: string | null;
  worktree_path?: string | null;
  artifacts_dir?: string | null;
  created_at: string;
  updated_at: string;
  closed_at?: string | null;
  current_approval_gate?: string | null;
}

export interface TaskArtifact {
  id: string;
  task_id: string;
  kind: string;
  version?: number | null;
  title: string;
  relative_path: string;
  content_type: string;
  content_hash?: string;
  created_at: string;
  updated_at: string;
  approved_at?: string | null;
}

export interface Approval {
  id: string;
  task_id: string;
  gate: string;
  status: "pending" | "approved" | "rejected" | "edited" | "cancelled" | string;
  artifact_ids: string[];
  requested_payload: Record<string, unknown>;
  user_comment?: string | null;
  created_at: string;
  resolved_at?: string | null;
}

export interface TaskEvent {
  id: string;
  task_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface RouteDecision {
  normalized_task?: string;
  intent?: string;
  task_kind?: string;
  complexity?: string;
  project_id?: string | null;
  project_name?: string | null;
  project_path?: string | null;
  workflow_id?: string | null;
  workflow_name?: string | null;
  risk_level?: string;
  risk_flags?: string[];
  approval_gates?: string[];
  warnings?: string[];
  rationale?: string;
  requires_spec?: boolean;
  [key: string]: unknown;
}

export interface CreateTaskRequest {
  message: string;
  source?: string | null;
  user_id?: string | null;
}

export interface CreateTaskResponse {
  task_id: string;
  status: TaskStatus | string;
  project_id?: string | null;
  workflow_id?: string | null;
  artifacts_dir?: string | null;
  current_approval_gate?: string | null;
}

export interface ListTasksParams {
  status?: string;
  project_id?: string;
  workflow_id?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface ListTasksResponse {
  items: Task[];
  total: number;
  limit: number;
  offset: number;
}

export interface ArtifactContentResponse {
  artifact: TaskArtifact;
  content: string;
}

export interface ApprovalDecisionInput {
  decision: "approve" | "reject";
  comment?: string | null;
}

export interface AgentRun {
  id: string;
  task_id: string;
  run_type: string;
  status: string;
  executor?: string | null;
  model?: string | null;
  started_at: string;
  finished_at?: string | null;
  iteration_count?: number;
  stop_reason?: string | null;
}

export interface AgentStep {
  id: string;
  run_id: string;
  step_index: number;
  step_type: string;
  status: string;
  input_summary?: string | null;
  output_summary?: string | null;
  artifact_ids?: string[];
  started_at: string;
  finished_at?: string | null;
  error?: string | null;
}
