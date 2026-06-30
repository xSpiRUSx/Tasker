export type TaskStatus =
  | "created"
  | "routing"
  | "routed"
  | "awaiting_clarification"
  | "awaiting_parent_task_clarification"
  | "awaiting_tool_health_override"
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
  | "awaiting_diff_reapproval"
  | "awaiting_scope_escalation_approval"
  | "changes_requested"
  | "correction_requested"
  | "classifying_correction"
  | "executing_correction"
  | "validating_correction"
  | "awaiting_correction_diff_approval"
  | "correction_blocked"
  | "awaiting_commit_approval"
  | "approved_for_commit"
  | "committing"
  | "deploy_prep"
  | "awaiting_deploy_approval"
  | "closed"
  | "failed"
  | "prompt_too_large"
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
  parent_task_id?: string | null;
  related_task_ids?: string[];
  correction_source?: string | null;
  branch_name?: string | null;
  worktree_path?: string | null;
  artifacts_dir?: string | null;
  created_at: string;
  updated_at: string;
  closed_at?: string | null;
  current_approval_gate?: string | null;
  runtime?: RuntimeSummary;
  latest_job?: TaskJob | null;
}

export interface RuntimeSummary {
  router: string;
  planner: string;
  executor: string;
  mode: "dry-run" | "live" | string;
}

export interface TaskJob {
  id: string;
  task_id: string;
  action: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | string;
  input?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface ModelDecision {
  id: string;
  task_id?: string | null;
  run_id?: string | null;
  operation: string;
  profile: string;
  selected_target: string;
  runtime: string;
  model: string;
  reasoning_effort?: string | null;
  reason: string;
  estimated_prompt_chars: number;
  max_prompt_chars: number;
  created_at: string;
}

export interface ModelCall {
  id: string;
  task_id?: string | null;
  run_id?: string | null;
  operation: string;
  runtime: string;
  provider?: string | null;
  model: string;
  reasoning_effort?: string | null;
  prompt_chars: number;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  cached_prompt_tokens?: number | null;
  reasoning_tokens?: number | null;
  total_tokens?: number | null;
  usage_source?: string | null;
  usage_is_estimated?: boolean;
  cost_usd?: number | null;
  latency_ms?: number | null;
  status?: string | null;
  error?: string | null;
  created_at: string;
}

export interface PromptBuild {
  id: string;
  task_id?: string | null;
  run_id?: string | null;
  operation: string;
  total_chars: number;
  budget_chars: number;
  included: Array<Record<string, unknown>>;
  excluded: Array<Record<string, unknown>>;
  status: string;
  created_at: string;
}

export interface ToolHealth {
  mode: string;
  project_id?: string | null;
  manual_review_required?: boolean;
  items: Record<string, boolean>;
  required_tools?: string[];
  unavailable_mcp?: string[];
  validation_profile?: string;
  test_commands?: string[];
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

export interface JobAcceptedResponse {
  accepted: boolean;
  job_id: string;
  task_id: string;
  status: string;
  action: string;
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

export interface CorrectionRequestInput {
  source_gate?: string;
  source_approval_id?: string | null;
  source_artifact_id?: string | null;
  comment: string;
  action: "run_without_new_plan" | "show_plan_first";
}

export interface CorrectionResponse {
  correction_id: string;
  mode: "micro_correction" | "minor_correction" | "spec_addendum" | "new_task" | string;
  status: string;
  approved_for_execution: boolean;
  requires_plan_approval: boolean;
  requires_spec_addendum: boolean;
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

export interface RoutingRule {
  id: string;
  rule_type: string;
  pattern_type: "exact" | "contains" | "regex" | "semantic_hint" | string;
  pattern: string;
  language?: string | null;
  target_route_type: string;
  target_workflow_id?: string | null;
  target_task_kind?: string | null;
  target_project_id?: string | null;
  constraints: string[];
  positive_examples: string[];
  negative_examples: string[];
  confidence?: number | null;
  priority: number;
  status: "pending" | "active" | "rejected" | "disabled" | string;
  source: string;
  source_task_id?: string | null;
  source_message?: string | null;
  hit_count: number;
  false_positive_count: number;
  created_at: string;
  updated_at: string;
}

export interface RoutingSuggestion {
  id: string;
  task_id?: string | null;
  message: string;
  classifier_result: Record<string, unknown>;
  suggested_rules: Array<Record<string, unknown>>;
  status: "pending" | "promoted" | "rejected" | string;
  created_at: string;
  resolved_at?: string | null;
}

export type ConfigRecord = Record<string, unknown>;

export interface RouterConfigDocument {
  projects_path: string;
  workflows_path: string;
  tools: ConfigRecord[];
  projects: ConfigRecord[];
  workflows: ConfigRecord[];
}
