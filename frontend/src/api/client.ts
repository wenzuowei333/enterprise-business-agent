export type UserPublic = {
  id: number;
  username: string;
  real_name: string;
  employee_code?: string | null;
  role: string;
  is_active: boolean;
  status: string;
  last_login_at?: string | null;
  last_login_ip?: string | null;
  avatar_url?: string | null;
  avatar_object_key?: string | null;
  avatar_updated_at?: string | null;
  disabled_reason?: string | null;
  cancelled_reason?: string | null;
  cancelled_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type Summary = {
  users: number;
  employees: number;
  roles: number;
  permissions: number;
  authority_root_rules: number;
  audit_logs: number;
  import_batches: number;
  customers: number;
  products: number;
  suppliers: number;
};

export type ExceptionCaseStatus = "open" | "action_required" | "processing" | "blocked" | "resolved" | "ignored";
export type ExceptionDomain = "inventory" | "receivable" | "master_data" | "import" | "system" | "crm" | "approval";
export type ExceptionDomainMode = "off" | "shadow" | "visible";
export type ExceptionDomainModes = {
  crm: ExceptionDomainMode;
  approval: ExceptionDomainMode;
};
export type ExceptionOccurrenceType = "baseline" | "new" | "reopened";
export type ExceptionFeedbackRating = "helpful" | "partial" | "incorrect";
export type ExceptionWorkScope = "mine" | "assigned" | "unassigned";
export type ExceptionSlaFilter = "overdue" | "due_soon" | "on_track" | "no_due_date";
export type ExceptionGroupBy = "rule" | "batch";

export type ExceptionDiagnosis = {
  id: number;
  evidence_version: string;
  root_cause_code?: string | null;
  summary?: string | null;
  confidence?: number | null;
  evidence_refs?: string[];
  impact?: string | Record<string, unknown> | null;
  recommended_steps?: string[];
  missing_evidence?: string[];
  disposition?: string | null;
  feedback_rating?: ExceptionFeedbackRating | null;
  feedback_note?: string | null;
  feedback_by_user_id?: number | null;
  feedback_at?: string | null;
  evidence_bytes?: number | null;
  evidence_approx_tokens?: number | null;
  evidence_truncated?: boolean | null;
  [key: string]: unknown;
};

export type ExceptionCaseItem = {
  id: number;
  case_no: string;
  domain: ExceptionDomain;
  diagnosis_supported?: boolean;
  rule_code: string;
  title: string;
  severity: string;
  status: ExceptionCaseStatus;
  occurrence_type: ExceptionOccurrenceType;
  occurrence_cycle?: number | null;
  rule_version?: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  resource_code?: string | null;
  resource_name?: string | null;
  source_type: string;
  source_id?: string | null;
  source_batch_kind?: ExceptionSourceBatchKind | null;
  source_batch_id?: number | null;
  data_date?: string | null;
  evidence_version: string;
  reason: string;
  initial_guidance?: string | null;
  action_path?: string | null;
  affected_rows: number;
  affected_amount?: string | number | null;
  affected_quantity?: string | number | null;
  assignee_user_id?: number | null;
  assignee_name?: string | null;
  due_at?: string | null;
  sla_status?: "overdue" | "due_soon" | "on_track" | "no_due_date" | null;
  is_mine?: boolean;
  detected_at: string;
  last_seen_at: string;
  resolved_at?: string | null;
  ignored_until?: string | null;
  resolution_note?: string | null;
  verified_at?: string | null;
  metadata?: Record<string, unknown>;
  diagnosis?: ExceptionDiagnosis | null;
  processing_kind?: "manual_diagnosis" | "scheduled_diagnosis" | "background_scan" | null;
  active_diagnosis_job?: ExceptionDiagnosisJob | null;
};

export type ExceptionSourceBatchKind = "import" | "inventory_check" | "legacy";

export type ExceptionCaseGroup = {
  key: string;
  label: string;
  group_by: ExceptionGroupBy;
  total: number;
  open: number;
  action_required: number;
  processing: number;
  blocked: number;
  critical: number;
  high: number;
  affected_rows: number;
  affected_quantity?: string | number | null;
  latest_seen_at?: string | null;
  sample_case_no?: string | null;
};

export type ExceptionAggregationGroup = {
  key: string;
  label: string;
  source_batch_kind?: ExceptionSourceBatchKind | null;
  source_batch_id?: number | null;
  count: number;
  critical: number;
  high: number;
  warning: number;
  overdue: number;
};

export type ExceptionAggregationResponse = {
  group_by: ExceptionGroupBy;
  groups: ExceptionAggregationGroup[];
  total: number;
  truncated: boolean;
};

export type ExceptionCasePage = {
  items: ExceptionCaseItem[];
  groups?: ExceptionCaseGroup[];
  total: number;
  limit: number;
  offset: number;
};

export type ExceptionSummary = {
  total: number;
  open: number;
  action_required: number;
  processing: number;
  blocked: number;
  resolved: number;
  ignored: number;
  unread_notifications: number;
  ai_enabled: boolean;
  ai_chat_enabled: boolean;
  ai_case_analysis_enabled: boolean;
  actions_enabled: boolean;
  manual_ai_enabled: boolean;
  scheduled_ai_enabled: boolean;
  full_scan_enabled: boolean;
  digest_enabled: boolean;
  by_domain: Record<string, number>;
  by_severity: Record<string, number>;
  by_occurrence: Record<string, number>;
  assigned_to_me?: number;
  mine?: number;
  unassigned?: number;
  overdue?: number;
  due_soon?: number;
};

export type ExceptionCaseDetail = ExceptionCaseItem & {
  evidence?: Record<string, unknown> | null;
  diagnoses: ExceptionDiagnosis[];
  actions: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
  active_diagnosis_job?: ExceptionDiagnosisJob | null;
};

export type ControlledActionRiskLevel = "low" | "medium" | "high";
export type ControlledExceptionActionType =
  | "rebuild_inventory_flow"
  | "rerun_inventory_check"
  | "rebuild_receivable_checks"
  | "rebuild_master_link_issues"
  | "revalidate_import_batch";

export type ControlledActionCatalogItem = {
  action_type: string;
  domain: string;
  label: string;
  risk_level: ControlledActionRiskLevel;
  required_permissions: string[];
  requires_confirmation: boolean;
  available: boolean;
  blockers: string[];
};

export type ControlledActionProposal = {
  id: number;
  proposal_no: string;
  domain: string;
  action_type: string;
  resource_type?: string | null;
  resource_id?: string | null;
  status: string;
  review_status: string;
  risk_level?: ControlledActionRiskLevel | null;
  requires_confirmation: boolean;
  parameters: Record<string, unknown>;
  impact: Record<string, unknown>;
  source_refs: string[];
  executable: boolean;
  blockers: string[];
  created_at: string;
  updated_at: string;
  reviewed_at?: string | null;
};

export type ControlledActionProposalPage = {
  items: ControlledActionProposal[];
  total: number;
  limit: number;
  offset: number;
};

export type ControlledActionValidation = {
  proposal: ControlledActionProposal;
  validation_token?: string | null;
  validation_expires_at?: string | null;
};

export type ControlledActionExecution = {
  execution_no: string;
  proposal_no: string;
  status: string;
  idempotency_key: string;
  attempts: number;
  executor_identity?: string | null;
  result: Record<string, unknown>;
  verification: Record<string, unknown>;
  error_code?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
};

export type ControlledActionExecutionPage = {
  items: ControlledActionExecution[];
  total: number;
  limit: number;
  offset: number;
};

export type ExceptionBatchResult = {
  updated_count: number;
  items: ExceptionCaseItem[];
};

export type ExceptionDiagnosisJob = {
  id: number;
  job_no: string;
  case_no: string;
  evidence_version: string;
  trigger_type: string;
  status: string;
  reused: boolean;
  requested_by_user_id?: number | null;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  case_title?: string | null;
  domain?: string | null;
  rule_code?: string | null;
  attempt_count?: number;
  max_attempts?: number;
  heartbeat_at?: string | null;
  next_retry_at?: string | null;
  attempts?: number;
  available_at?: string | null;
  lease_expires_at?: string | null;
  lease_owner?: string | null;
  cancel_requested_at?: string | null;
  cancel_requested_by_user_id?: number | null;
  requested_by_name?: string | null;
  cancellable?: boolean;
  retryable?: boolean;
};

export type ExceptionDiagnosisJobPage = {
  items: ExceptionJobItem[];
  total: number;
  limit: number;
  offset: number;
};

export type ExceptionJobItem = {
  id: number;
  job_no: string;
  job_kind: "diagnosis" | "background";
  job_type: string;
  case_no?: string | null;
  evidence_version?: string | null;
  trigger_type?: string | null;
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  attempts: number;
  requested_by_user_id?: number | null;
  requested_by_name?: string | null;
  available_at?: string | null;
  lease_owner?: string | null;
  lease_expires_at?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
};

export type ExceptionActionType =
  | "rebuild_inventory_flow"
  | "rerun_inventory_check"
  | "rebuild_receivable_checks"
  | "rebuild_master_link_issues"
  | "revalidate_import_batch";

export type ExceptionAction = {
  id: number;
  action_no: string;
  case_no: string;
  action_type: string;
  status: string;
  allowed: boolean;
  blockers: string[];
  impact: Record<string, unknown>;
  evidence_version: string;
  validation_token?: string | null;
  validation_expires_at?: string | null;
  result?: Record<string, unknown> | null;
  verification?: Record<string, unknown> | null;
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
};

export type ExceptionNotification = {
  id: number;
  case_no: string;
  notification_type: string;
  title: string;
  message: string;
  is_read: boolean;
  read_at?: string | null;
  acknowledged_at?: string | null;
  created_at: string;
};

export type ExceptionPolicy = {
  policy_key: string;
  is_enabled: boolean;
  manual_ai_enabled: boolean;
  scheduled_ai_enabled: boolean;
  full_scan_enabled: boolean;
  digest_enabled: boolean;
  full_scan_cron: string;
  digest_cron: string;
  ai_daily_limit: number;
  ai_batch_limit: number;
  manual_ai_daily_limit: number;
  scheduled_ai_daily_limit: number;
  scheduled_ai_batch_limit: number;
  ai_concurrency: number;
  stale_diagnosis_hours: number;
  domain_modes: ExceptionDomainModes;
  settings: Record<string, unknown>;
  updated_at: string;
};

export type ExceptionScanResult = {
  domains: string[];
  requested_domains: string[];
  domain_modes: Partial<ExceptionDomainModes>;
  scan_trigger: "baseline";
  scanned: number;
  created: number;
  new: number;
  reopened: number;
  evidence_updated: number;
  resolved: number;
};

export type ExceptionBaselineScanResponse = {
  scan_reference: string;
  audit_id: number;
  domain: "crm" | "approval";
  domain_mode: "shadow";
  shadow_cycle: number;
  policy_updated_at: string;
  reused: boolean;
  result: ExceptionScanResult;
};

export type ExceptionRuleQualityMetrics = {
  total: number;
  active: number;
  baseline: number;
  new: number;
  reopened: number;
  ignored: number;
  resolved: number;
  evidence_changed_events: number;
  latest_seen_at?: string | null;
  false_positive_rate?: number | null;
};

export type ExceptionDomainRuleQuality = ExceptionRuleQualityMetrics & {
  domain: ExceptionDomain;
  domain_mode: ExceptionDomainMode;
  scan_job_metrics_available: boolean;
  queued_scan_jobs?: number | null;
  failed_scan_jobs?: number | null;
  scan_latency_p95_ms?: number | null;
};

export type ExceptionRuleQuality = ExceptionRuleQualityMetrics & {
  domain: ExceptionDomain;
  domain_mode: ExceptionDomainMode;
  rule_code: string;
  rule_version: string;
};

export type ExceptionRuleQualityResponse = {
  generated_at: string;
  scan_job_window_days: number;
  scan_job_window_start: string;
  scan_job_window_end: string;
  domains: ExceptionDomainRuleQuality[];
  rules: ExceptionRuleQuality[];
};

function normalizeExceptionPolicy(policy: ExceptionPolicy): ExceptionPolicy {
  return {
    ...policy,
    domain_modes: {
      crm: policy.domain_modes?.crm ?? "off",
      approval: policy.domain_modes?.approval ?? "off",
    },
  };
}

export type ExceptionVerificationSnapshot = {
  status?: ExceptionCaseStatus | string | null;
  evidence_version?: string | null;
  affected_rows?: number | null;
  affected_amount?: string | number | null;
  affected_quantity?: string | number | null;
  checked_at?: string | null;
  summary?: string | null;
};

export type ExceptionVerificationResult = {
  case: ExceptionCaseItem;
  resolved: boolean;
  before?: ExceptionVerificationSnapshot | null;
  after?: ExceptionVerificationSnapshot | null;
  note?: string | null;
  evidence_changed?: boolean;
  scan_result?: Record<string, unknown> | null;
};

export type ExceptionCircuitStatus = {
  open: boolean;
  consecutive_failures: number;
  retry_after_seconds: number;
  stale: boolean;
  source: "ai_worker";
};

export type ExceptionOpsSummary = {
  generated_at: string;
  global_ai_enabled: boolean;
  provider_configured: boolean;
  provider_host?: string | null;
  model?: string | null;
  circuit: ExceptionCircuitStatus | null;
  diagnosis_jobs_by_status: Record<string, number>;
  diagnosis_jobs_by_trigger: Record<string, Record<string, number>>;
  background_jobs_by_status: Record<string, number>;
  manual_queue_depth: number;
  scheduled_queue_depth: number;
  background_queue_depth: number;
  oldest_manual_queued_at?: string | null;
  oldest_scheduled_queued_at?: string | null;
  oldest_background_queued_at?: string | null;
  heartbeats: Array<{
    service_type: "worker" | "ai_worker" | "scheduler";
    instance_id: string;
    started_at: string;
    last_heartbeat_at: string;
    is_stale: boolean;
    is_healthy?: boolean | null;
    heartbeat_age_seconds?: number | null;
    metadata?: Record<string, unknown>;
  }>;
  policy: {
    is_enabled: boolean;
    manual_ai_enabled: boolean;
    scheduled_ai_enabled: boolean;
    full_scan_enabled: boolean;
    digest_enabled: boolean;
    ai_concurrency: number;
    scheduled_ai_batch_limit: number;
  };
  manual_budget: ExceptionOpsBudget;
  scheduled_budget: ExceptionOpsBudget;
  last_full_scan_at?: string | null;
  last_digest_at?: string | null;
  last_scan_duration_ms?: number | null;
  last_scan_created?: number;
  last_scan_new?: number;
  last_scan_reopened?: number;
  last_scan_evidence_updated?: number;
  last_scan_resolved?: number;
  last_scan_scanned?: number;
  diagnosis_completed_24h?: number;
  diagnosis_failed_24h?: number;
};

export type ExceptionOpsBudget = {
  limit: number;
  used: number;
  remaining: number | null;
  unlimited: boolean;
};

export type ExceptionDiagnosisQualityBucket = {
  key: string;
  label?: string | null;
  diagnoses: number;
  rated: number;
  helpful: number;
  partial: number;
  incorrect: number;
  positive_rate?: number | null;
  average_confidence?: number | null;
  average_latency_ms?: number | null;
  total_tokens: number;
  usage_reported_count: number;
  usage_missing_count: number;
  usage_completeness_rate?: number | null;
};

export type ExceptionDiagnosisQualityRule = {
  domain?: string | null;
  rule_code: string;
  diagnoses: number;
  feedback_count: number;
  helpful: number;
  partial: number;
  incorrect: number;
  helpful_rate?: number | null;
  average_confidence?: number | null;
  average_resolution_hours?: number | null;
};

export type ExceptionDiagnosisQuality = {
  generated_at?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  total_diagnoses: number;
  feedback_count: number;
  feedback_rate?: number | null;
  helpful_rate?: number | null;
  average_confidence?: number | null;
  average_resolution_hours?: number | null;
  by_feedback: Record<string, number>;
  by_disposition: Record<string, number>;
  by_root_cause_code: ExceptionDiagnosisQualityBucket[];
  by_contract_version: ExceptionDiagnosisQualityBucket[];
  by_domain: ExceptionDiagnosisQualityBucket[];
  by_rule: ExceptionDiagnosisQualityBucket[];
  by_model: ExceptionDiagnosisQualityBucket[];
  by_prompt_version: ExceptionDiagnosisQualityBucket[];
  rules: ExceptionDiagnosisQualityRule[];
  feedback_coverage_rate?: number | null;
  rated_diagnoses?: number;
  helpful?: number;
  partial?: number;
  incorrect?: number;
  unrated?: number;
  positive_rate?: number | null;
  evidence_citation_rate?: number | null;
  evidence_reference_valid_rate?: number | null;
  average_latency_ms?: number | null;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  usage_reported_count: number;
  usage_missing_count: number;
  usage_completeness_rate?: number | null;
};

export type ApiErrorPayload = {
  error_code?: string | null;
  message?: string | null;
  request_id?: string | null;
  module?: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  case_no?: string | null;
  retryable?: boolean | null;
  action_path?: string | null;
  field_errors?: Array<{ field?: string | null; message?: string | null }>;
};

export const API_ERROR_EVENT = "project-base:api-error";

export type ApiErrorEventDetail = {
  error: ApiError;
  method: string;
  path: string;
};

export const AUTH_EXPIRED_EVENT = "project-base:auth-expired";

export class ApiError extends Error {
  readonly status: number;
  readonly error_code?: string | null;
  readonly request_id?: string | null;
  readonly module?: string | null;
  readonly resource_type?: string | null;
  readonly resource_id?: string | null;
  readonly case_no?: string | null;
  readonly retryable?: boolean | null;
  readonly action_path?: string | null;
  readonly field_errors: Array<{ field?: string | null; message?: string | null }>;

  constructor(status: number, message: string, payload: ApiErrorPayload = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.error_code = payload.error_code;
    this.request_id = payload.request_id;
    this.module = payload.module;
    this.resource_type = payload.resource_type;
    this.resource_id = payload.resource_id;
    this.case_no = payload.case_no;
    this.retryable = payload.retryable;
    this.action_path = payload.action_path;
    this.field_errors = payload.field_errors ?? [];
  }
}

export type MobileOperationsOverview = {
  days: number;
  generated_at: string;
  active_devices: number;
  total_sessions: number;
  version_distribution: Record<string, number>;
  operations: Record<string, number>;
  sync_success_rate: number;
  pending_operations: number;
  conflicts: number;
  telemetry: {
    event_counts: Record<string, number>;
    error_codes: Record<string, number>;
    api_p50_ms?: number | null;
    api_p95_ms?: number | null;
    recent_errors: Array<{
      event_type: string;
      code?: string | null;
      route?: string | null;
      request_id?: string | null;
      app_version?: string | null;
      occurred_at?: string | null;
    }>;
  };
  latest_operations: Array<{
    id: number;
    action_type: string;
    status: string;
    resource_type?: string | null;
    resource_id?: string | null;
    device_id: string;
    created_at?: string | null;
  }>;
};

export type MobileAdminDevice = {
  id: number;
  device_id: string;
  device_name?: string | null;
  device_model?: string | null;
  app_version?: string | null;
  android_version?: string | null;
  last_used_at?: string | null;
  last_sync_at?: string | null;
  revoked_at?: string | null;
  user_id: number;
  username: string;
  user_label: string;
};

export type MobileAdminDevicePage = {
  items: MobileAdminDevice[];
  total: number;
  limit: number;
  offset: number;
};

export type MobileFeedbackRow = {
  id: number;
  user_id: number;
  user_label?: string | null;
  category: string;
  description: string;
  current_route?: string | null;
  request_id?: string | null;
  app_version?: string | null;
  android_version?: string | null;
  device_model?: string | null;
  screenshot_path?: string | null;
  status: "open" | "processing" | "resolved" | "closed";
  handler_label?: string | null;
  resolution?: string | null;
  created_at: string;
};

export type MobileFeedbackPage = {
  items: MobileFeedbackRow[];
  total: number;
  limit: number;
  offset: number;
};

export type MobileAdoptionOverview = {
  days: number;
  eligible_users: number;
  weekly_active_users: number;
  weekly_active_rate: number;
  feature_usage: Record<string, number>;
  followup_form_avg_ms?: number | null;
  followup_form_p50_ms?: number | null;
  feedback: Record<string, number>;
  feedback_resolution_avg_hours?: number | null;
  ai_draft_success_rate?: number | null;
  ai_draft_adoption_rate?: number | null;
};

export type DashboardRange = "today" | "7d" | "30d" | "month";

export type DashboardTarget = {
  page: string;
  path?: string;
};

export type DashboardTone = "ok" | "warn" | "bad" | "neutral";

export type DashboardConclusion = {
  tone: DashboardTone;
  title: string;
  detail: string;
  target: DashboardTarget;
};

export type DashboardMetric = {
  key: string;
  label: string;
  value: number;
  sub_value: string;
  tone: DashboardTone;
  target: DashboardTarget;
};

export type DashboardTrendPoint = {
  date: string;
  label: string;
  sales_amount: number;
  gross_profit: number;
  purchase_amount: number;
  inventory_cost: number;
  account_balance: number;
};

export type DashboardActionItem = {
  id: string;
  title: string;
  detail: string;
  severity: DashboardTone;
  badge: string;
  target: DashboardTarget;
};

export type DashboardRiskCell = {
  key: "normal" | "watch" | "abnormal" | "pending" | string;
  value: number;
  tone: DashboardTone;
  target: DashboardTarget;
  label?: string;
  description?: string;
  effective_date?: string | null;
};

export type DashboardRiskRow = {
  key: string;
  label: string;
  cells: DashboardRiskCell[];
};

export type DashboardRiskMatrix = {
  columns: Array<{ key: string; label: string }>;
  rows: DashboardRiskRow[];
};

export type DashboardBusinessFlowNode = {
  key: string;
  label: string;
  value: number;
  risk: number;
  detail: string;
  target: DashboardTarget;
};

export type DashboardRunRecord = {
  id: number;
  batch_no?: string;
  file_type?: string;
  status?: string;
  total_rows?: number;
  error_rows?: number;
  uploaded_at?: string | null;
  role_code?: string | null;
  action_type?: string;
  resource_type?: string;
  created_at?: string | null;
  target: DashboardTarget;
};

export type DashboardOverview = {
  range: DashboardRange;
  date_from: string;
  date_to: string;
  generated_at: string;
  conclusion: DashboardConclusion;
  metrics: DashboardMetric[];
  trend: DashboardTrendPoint[];
  actions: DashboardActionItem[];
  risk_matrix: DashboardRiskMatrix;
  business_flow: DashboardBusinessFlowNode[];
  run_records: {
    imports: DashboardRunRecord[];
    audits: DashboardRunRecord[];
  };
};

export type ImportBatch = {
  id: number;
  batch_no: string;
  file_name: string;
  file_type: string;
  data_date?: string | null;
  uploaded_by?: number | null;
  uploaded_at?: string | null;
  status: string;
  total_rows: number;
  success_rows: number;
  error_rows: number;
  mapping_json?: Record<string, unknown> | null;
};

export type ImportBatchQuery = {
  file_type?: string;
  data_date_from?: string;
  data_date_to?: string;
  limit?: number;
};

export type ImageProcessingTemplate = {
  key: string;
  label: string;
  description: string;
  output_width: number;
  output_height: number;
  output_suffix: string;
  watermark_opacity: number;
};

export type ImageProcessingConfig = {
  templates: Record<string, ImageProcessingTemplate>;
  max_files: number;
  max_bytes: number;
  retention_days: number;
  tool_available: boolean;
  tool_status: string;
};

export type ImageProcessingJob = {
  id: number;
  job_no: string;
  created_by_user_id?: number | null;
  created_by_username?: string | null;
  template_type: string;
  status: string;
  input_count: number;
  success_count: number;
  failed_count: number;
  skipped_count: number;
  options?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
  created_at: string;
  updated_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type ImageProcessingFile = {
  id: number;
  job_id: number;
  original_filename: string;
  output_filename?: string | null;
  content_type?: string | null;
  size_bytes?: number | null;
  sort_order: number;
  status: string;
  error_message?: string | null;
  download_url?: string | null;
  preview_url?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ImageProcessingJobDetail = {
  job: ImageProcessingJob;
  files: ImageProcessingFile[];
  download_all_url?: string | null;
};

export type ImageProcessingJobCreateResult = {
  job_id: number;
  job_no: string;
  status: string;
};

export type DataCalendarRuleRow = {
  id: number;
  rule_code: string;
  file_type: string;
  label: string;
  action_layer: "blue" | "green" | "orange" | "red" | "gray" | string;
  frequency: "daily" | "ondemand" | string;
  deadline_hour?: number | null;
  owner_role: string;
  owner_user_ids?: number[] | null;
  is_required: boolean;
  is_enabled: boolean;
  sort_order: number;
  remark?: string | null;
  created_at: string;
  updated_at: string;
};

export type DataCalendarRulePayload = Omit<
  DataCalendarRuleRow,
  "id" | "created_at" | "updated_at"
> & { id?: number | null };

export type DataCalendarReminderItem = {
  rule_code: string;
  file_type: string;
  label: string;
  status: string;
  detail: string;
  responsible_user_ids: number[];
  missing_responsible_user_ids: number[];
  latest_batch_no?: string | null;
};

export type DataCalendarReminderRequest = {
  data_date: string;
  reminder_type?: string;
  items: DataCalendarReminderItem[];
  message?: string | null;
};

export type DataCalendarReminderResponse = {
  status: string;
  audit_id: number;
  resource_id: string;
  reminder_count: number;
};

export type DataCalendarCoverageRow = {
  data_date: string;
  file_type: string;
  status: string;
  row_count: number;
  batch_ids: number[];
  batch_nos: string[];
  latest_batch_id?: number | null;
  latest_batch_no?: string | null;
  latest_uploaded_by?: number | null;
  source: string;
};

export type AttentionState = "normal" | "needs_attention";

export type AttentionReason = {
  code: string;
  label: string;
};

export type AttentionReasonCount = AttentionReason & {
  count: number;
};

export type AttentionSummary = {
  total: number;
  normal: number;
  needs_attention: number;
  by_reason: AttentionReasonCount[];
  effective_date?: string | null;
  batch_id?: number | null;
};

export type AttentionAnnotated = {
  attention_state?: AttentionState | null;
  attention_reasons?: AttentionReason[] | null;
};

export type MasterRow = Record<
  string,
  string | number | boolean | string[] | null | undefined
> &
  AttentionAnnotated;

export type MasterPage = {
  items: MasterRow[];
  total: number;
  limit: number;
  offset: number;
  attention_summary?: AttentionSummary | null;
};

export type SalesDetailRow = Record<string, string | number | null | undefined>;
export type InventorySnapshotRow = Record<
  string,
  string | number | null | undefined
> &
  AttentionAnnotated;
export type PurchaseDetailRow = Record<
  string,
  string | number | null | undefined
>;
export type AccountBalanceRow = Record<
  string,
  string | number | null | undefined
>;

export type SettlementUnitResolveResult = {
  input: { code?: string | null; name?: string | null };
  direction: "customer" | "supplier" | "unknown";
  best_kind: "customer" | "supplier" | "unknown";
  confidence: number;
  target?: {
    kind: "customers" | "suppliers";
    code: string;
    name: string;
  } | null;
  reason: string;
  candidates: Array<{
    kind: "customer" | "supplier";
    code: string;
    name: string;
    score: number;
    match_type: string;
    reasons: string[];
  }>;
};

export type SalesDetailSummary = {
  rows: number;
  documents: number;
  customers: number;
  products: number;
  sale_qty_base?: string | number | null;
  amount_tax_total?: string | number | null;
  amount_after_discount?: string | number | null;
  cost_amount?: string | number | null;
  gross_profit?: string | number | null;
  gross_margin_rate?: string | number | null;
  inventory_abnormal_rows?: number;
  zero_stock_sales?: number;
  negative_stock_sales?: number;
  without_stock_sales?: number;
};

export type SalesDetailPage = {
  items: SalesDetailRow[];
  total: number;
  limit: number;
  offset: number;
  summary: SalesDetailSummary;
};

export type InventorySnapshotSummary = {
  rows: number;
  products: number;
  suppliers: number;
  warehouses?: number;
  stock_qty?: string | number | null;
  stock_inventory_qty?: string | number | null;
  locked_base_qty?: string | number | null;
  cost_amount?: string | number | null;
  positive_rows: number;
  zero_rows: number;
  negative_rows: number;
  locked_rows: number;
  abnormal_rows: number;
};

export type InventorySnapshotPage = {
  items: InventorySnapshotRow[];
  total: number;
  limit: number;
  offset: number;
  summary: InventorySnapshotSummary;
  attention_summary?: AttentionSummary | null;
};

export type InventoryCheckBatch = {
  id: number;
  batch_no: string;
  file_name: string;
  data_date?: string | null;
  uploaded_by?: number | null;
  status: string;
  total_rows: number;
  matched_rows: number;
  difference_rows: number;
  missing_in_system_rows: number;
  missing_in_upload_rows: number;
  invalid_rows: number;
  duplicate_upload_rows: number;
  raw_file_path?: string | null;
  header_json?: string[] | null;
  mapping_json?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type InventoryCheckResult = {
  id: number;
  batch_id: number;
  result_type:
    | "quantity_mismatch"
    | "missing_in_system"
    | "missing_in_upload"
    | "invalid_row"
    | "missing_product_master"
    | string;
  product_code?: string | null;
  product_name?: string | null;
  warehouse_name?: string | null;
  warehouse_scope?: string | null;
  platform_stock_qty?: string | number | null;
  system_stock_qty?: string | number | null;
  diff_qty?: string | number | null;
  system_data_date?: string | null;
  system_basis_type?: string | null;
  system_basis_label?: string | null;
  duplicate_in_upload: boolean;
  source_row_numbers: number[];
  platform_row_json?: Record<string, unknown> | null;
  system_snapshot_json?: Record<string, unknown> | null;
  created_at?: string | null;
};

export type InventoryFlowRow = {
  id: number;
  data_date?: string | null;
  warehouse_name?: string | null;
  warehouse_scope?: string | null;
  product_code?: string | null;
  product_name?: string | null;
  opening_stock_qty?: string | number | null;
  purchase_qty?: string | number | null;
  sales_qty?: string | number | null;
  calculated_closing_qty?: string | number | null;
  snapshot_stock_qty?: string | number | null;
  diff_qty?: string | number | null;
  anomaly_type: string;
  anomaly_flags: string[];
  source_batch_ids: number[];
  source_counts?: Record<string, number>;
};

export type InventoryFlowSummary = {
  total: number;
  abnormal: number;
  normal: number;
  warehouses: number;
  products: number;
  by_type: Record<string, number>;
};

export type InventoryFlowPage = {
  items: InventoryFlowRow[];
  total: number;
  limit: number;
  offset: number;
  summary: InventoryFlowSummary;
};

export type SalesInventoryStatus = {
  sales_detail_id: number;
  flow_id?: number | null;
  anomaly_type: string;
  label: string;
  anomaly_flags: string[];
};

export type InventoryCheckResultPage = {
  items: InventoryCheckResult[];
  total: number;
  limit: number;
  offset: number;
  summary: Record<string, number>;
};

export type InventoryCheckBatchPage = {
  items: InventoryCheckBatch[];
  total: number;
  limit: number;
  offset: number;
};

export type PurchaseDetailSummary = {
  rows: number;
  documents: number;
  suppliers: number;
  products: number;
  purchase_qty_base?: string | number | null;
  amount_tax_total?: string | number | null;
  amount_after_discount?: string | number | null;
  purchase_amount?: string | number | null;
  discount_amount?: string | number | null;
  tax_amount?: string | number | null;
};

export type PurchaseDetailPage = {
  items: PurchaseDetailRow[];
  total: number;
  limit: number;
  offset: number;
  summary: PurchaseDetailSummary;
};

export type AccountBalanceSummary = {
  rows: number;
  settlement_units: number;
  current_opening_balance?: string | number | null;
  current_amount?: string | number | null;
  current_closing_balance?: string | number | null;
  ar_balance?: string | number | null;
  ap_balance?: string | number | null;
  advance_receipt_balance?: string | number | null;
  advance_payment_balance?: string | number | null;
  ar_rows: number;
  ap_rows: number;
  advance_receipt_rows: number;
  advance_payment_rows: number;
  zero_rows: number;
  risk_rows: number;
};

export type AccountBalancePage = {
  items: AccountBalanceRow[];
  total: number;
  limit: number;
  offset: number;
  summary: AccountBalanceSummary;
};

export type AccountLedgerSummary = {
  rows: number;
  settlement_units: number;
  documents: number;
  received_amount?: string | number | null;
  ar_amount?: string | number | null;
  paid_amount?: string | number | null;
  ap_amount?: string | number | null;
  opening_rows: number;
  closing_rows: number;
  transaction_rows: number;
  non_zero_ar_rows: number;
  non_zero_ap_rows: number;
  latest_data_date?: string | null;
};

export type AccountLedgerRow = Record<
  string,
  string | number | null | undefined
> &
  AttentionAnnotated;

export type AccountLedgerPage = {
  items: AccountLedgerRow[];
  total: number;
  limit: number;
  offset: number;
  summary: AccountLedgerSummary;
  attention_summary?: AttentionSummary | null;
};

export type ReceivableSummary = {
  latest_data_date?: string | null;
  rows: number;
  customers: number;
  ar_balance?: string | number | null;
  unmatched_rows: number;
  risk_rows: number;
};

export type ReceivableRow = {
  id: number;
  batch_id: number;
  row_number: number;
  data_date?: string | null;
  customer_code?: string | null;
  customer_name?: string | null;
  matched_customer_code?: string | null;
  matched_customer_name?: string | null;
  match_status: string;
  ar_opening_balance?: string | number | null;
  ar_current_amount?: string | number | null;
  received_amount?: string | number | null;
  unreceived_amount?: string | number | null;
  ar_balance?: string | number | null;
  aging_label?: string | null;
  overdue_days?: number | null;
  salesperson_name?: string | null;
  department_name?: string | null;
  remark?: string | null;
  created_at?: string | null;
};

export type ReceivablePage = {
  items: ReceivableRow[];
  total: number;
  limit: number;
  offset: number;
  summary: ReceivableSummary;
};

export type ReceivableCheckResult = {
  id: number;
  batch_id: number;
  receivable_snapshot_id?: number | null;
  result_type: string;
  result_label: string;
  severity: string;
  data_date?: string | null;
  customer_code?: string | null;
  customer_name?: string | null;
  matched_customer_code?: string | null;
  matched_customer_name?: string | null;
  receivable_ar_balance?: string | number | null;
  account_ar_balance?: string | number | null;
  previous_ar_balance?: string | number | null;
  diff_amount?: string | number | null;
  overdue_days?: number | null;
  recent_sales_amount?: string | number | null;
  message?: string | null;
  source_json?: Record<string, unknown> | null;
  created_at?: string | null;
};

export type ReceivableCheckResultPage = {
  items: ReceivableCheckResult[];
  total: number;
  limit: number;
  offset: number;
  summary: Record<string, number>;
};

export type ContextBlock<TPage> = {
  available: boolean;
  reason?: string | null;
  page?: TPage | null;
};

export type ProcessDetailContextKind =
  | "sales"
  | "purchase"
  | "inventory"
  | "account";

export type ProcessDetailContextResult = {
  kind: ProcessDetailContextKind;
  limit: number;
  sales: ContextBlock<SalesDetailPage>;
  purchase: ContextBlock<PurchaseDetailPage>;
  inventory: ContextBlock<InventorySnapshotPage>;
  account: ContextBlock<AccountBalancePage>;
};

export type CustomerPortraitTag = {
  key: string;
  label: string;
  value: string;
  tone: "ok" | "warn" | "bad" | "neutral";
  detail: string;
};

export type CustomerPortraitTagsResult = {
  rule_version: string;
  generated_at: string;
  data_cutoff_date?: string | null;
  match_confidence: "strong" | "weak";
  customer: Record<string, string | number | null | undefined>;
  metrics: Record<string, string | number | null | undefined>;
  quality: {
    status: "ok" | "partial";
    issues: string[];
  };
  tags: CustomerPortraitTag[];
  payment?: {
    rule_version: string;
    score: number;
    level: string;
    level_tone: "ok" | "warn" | "bad" | "neutral";
    action: string;
    tags: CustomerPortraitTag[];
    score_reasons: string[];
    quality_issues: string[];
    metrics: Record<string, string | number | boolean | null | undefined>;
  };
  profile?: {
    rule_version: string;
    headline: string;
    positioning: string;
    conclusions: string[];
    keywords: string[];
    evidence: Record<string, string | number | null | undefined>;
    sections: Array<{
      key: string;
      title: string;
      summary: string;
      items?: Array<{ label: string; value: string; detail?: string | null }>;
      bullets?: string[];
    }>;
  };
  snapshot?: {
    id: number;
    status: string;
    source: string;
    task_no?: string | null;
    generated_at?: string | null;
    period_start?: string | null;
    period_end?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
  };
  task?: {
    id: number;
    task_no: string;
    task_type: string;
    status: string;
    customer_code?: string | null;
    total_customers: number;
    success_count: number;
    failed_count: number;
    started_at?: string | null;
    finished_at?: string | null;
  };
};

export type ProcessCategoryNode = {
  id: string;
  label: string;
  path: string[];
  count: number;
  abnormal_count: number;
  children: ProcessCategoryNode[];
};

export type MasterCategoryNode = {
  id: string;
  label: string;
  path: string[];
  count: number;
  abnormal_count: number;
  search_text?: string;
  category_id?: number | null;
  node_code?: string | null;
  persisted?: boolean;
  is_enabled?: boolean;
  sort_order?: number;
  remark?: string | null;
  children: MasterCategoryNode[];
};

export type MasterCategoryNodeRow = {
  id: number;
  node_code: string;
  kind: "customers" | "products" | "customer_groups" | string;
  label: string;
  parent_id?: number | null;
  sort_order: number;
  is_enabled: boolean;
  remark?: string | null;
  created_by_user_id?: number | null;
  updated_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type MasterCategoryNodePayload = {
  label: string;
  parent_id?: number | null;
  sort_order?: number;
  is_enabled?: boolean;
  remark?: string | null;
};

export type MasterCategoryBindingRow = {
  id: number;
  category_id: number;
  resource_type: string;
  resource_code: string;
  is_primary: boolean;
  sort_order: number;
  source?: string | null;
  created_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type CustomerUpdatePayload = {
  customer_name?: string | null;
  customer_short_name?: string | null;
  customer_type?: string | null;
  region?: string | null;
  salesperson_employee_code?: string | null;
  salesperson_name?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  contact_channel?: string | null;
  customer_group_name?: string | null;
  address?: string | null;
  status?: string | null;
  profile_updated_at?: string | null;
  base_remark?: string | null;
  customer_tags?: string[] | null;
};

export type CustomerCreatePayload = CustomerUpdatePayload & {
  customer_code: string;
  customer_name: string;
};

export type CustomerTagColorKey =
  | "blue"
  | "green"
  | "cyan"
  | "yellow"
  | "red"
  | "purple"
  | "pink"
  | "gray";

export type CustomerTagRow = {
  id: number;
  name: string;
  color_key: CustomerTagColorKey;
  is_active: boolean;
  usage_count: number;
  created_by_user_id?: number | null;
  created_by_name?: string | null;
  created_at: string;
  updated_at: string;
};

export type CustomerTagPayload = {
  name: string;
  color_key: CustomerTagColorKey;
};

export type CustomerTagUpdatePayload = {
  name?: string;
  color_key?: CustomerTagColorKey;
  is_active?: boolean;
};

export type StructuredCustomerTag = CustomerTagRow & {
  stable_code?: string | null;
  category_key?: string | null;
  category_name?: string | null;
  group_code?: string | null;
  group_name?: string | null;
  catalog_version_id?: number | null;
  sort_order: number;
  selection_rule: string;
  mutual_exclusion_key?: string | null;
  applicability_json?: { attribute_types?: string[] } | null;
  is_formal: boolean;
  replaced_by_tag_id?: number | null;
};

export type CustomerTagCatalogVersion = {
  id: number;
  version_code: string;
  name: string;
  status: string;
  description?: string | null;
  activated_at?: string | null;
  retired_at?: string | null;
  created_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type CustomerTagCatalogDefinitionPayload = {
  stable_code: string;
  name: string;
  color_key: CustomerTagColorKey;
  category_key:
    | "classification"
    | "product_opportunity"
    | "purchase_characteristic"
    | "delivery_requirement";
  category_name: string;
  group_code?: string | null;
  group_name?: string | null;
  sort_order?: number;
  selection_rule?: "single" | "multi";
  mutual_exclusion_key?: string | null;
  attribute_types?: Array<"long_term" | "temporary">;
};

export type CustomerTagGovernanceSettings = {
  id: number;
  settings_key: string;
  default_reviewer_user_id?: number | null;
  backup_reviewer_user_id?: number | null;
  tag_workflow_enabled: boolean;
  recommendation_enabled: boolean;
  fulfillment_enabled: boolean;
  review_reminder_days: number;
  updated_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type CustomerTagRuleVersion = {
  id: number;
  rule_code: string;
  version_no: number;
  name: string;
  status: string;
  parameters_json: Record<string, unknown>;
  activated_at?: string | null;
  created_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type CustomerTagRecommendation = {
  id: number;
  customer_code: string;
  tag_id: number;
  tag_name?: string | null;
  rule_version_id?: number | null;
  statistics_start?: string | null;
  statistics_end?: string | null;
  metrics_json: Record<string, unknown>;
  confidence: number | string;
  status: string;
  manual_result?: string | null;
  manual_note?: string | null;
  reviewed_by_user_id?: number | null;
  reviewed_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type CustomerTagAssignment = {
  id: number;
  customer_code: string;
  tag_id: number;
  tag_code?: string | null;
  tag_name?: string | null;
  category_key?: string | null;
  category_name?: string | null;
  group_code?: string | null;
  group_name?: string | null;
  color_key?: CustomerTagColorKey | null;
  attribute_type: string;
  source: string;
  evidence: string;
  effective_date: string;
  review_date?: string | null;
  status: string;
  owner_user_id?: number | null;
  owner_user_label?: string | null;
  is_primary: boolean;
  details_json?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type CustomerTagProfile = {
  customer_code: string;
  customer_name: string;
  assignments: CustomerTagAssignment[];
  by_category: Record<string, CustomerTagAssignment[]>;
  legacy_tags: Array<{
    id: number;
    legacy_tag_name: string;
    target_tag_id?: number | null;
    target_tag_name?: string | null;
    confidence?: number | null;
    rationale?: string | null;
    status: string;
  }>;
  review_due_count: number;
  compatibility_tags: string[];
};

export type TaggedCustomerRow = {
  customer_code: string;
  customer_name: string;
  customer_type?: string | null;
  region?: string | null;
  salesperson_name?: string | null;
  status?: string | null;
  customer_tags: string[];
  assignments: Array<{
    assignment_id: number;
    tag_id: number;
    tag_name: string;
    category_key?: string | null;
    group_code?: string | null;
    group_name?: string | null;
    color_key?: CustomerTagColorKey | null;
    owner_user_id?: number | null;
    review_date?: string | null;
    is_primary: boolean;
  }>;
};

export type CustomerTagChangeItemPayload = {
  action: "add" | "update" | "cancel";
  assignment_id?: number | null;
  tag_id: number;
  attribute_type?: "long_term" | "temporary";
  source?:
    | "business_input"
    | "customer_confirmed"
    | "management_input"
    | "system_recommendation";
  evidence: string;
  effective_date?: string;
  review_date?: string | null;
  owner_user_id?: number | null;
  is_primary?: boolean;
  details_json?: Record<string, unknown>;
};

export type CustomerTagChangeRequest = {
  id: number;
  request_no: string;
  customer_code: string;
  customer_name?: string | null;
  applicant_user_id?: number | null;
  applicant_user_label?: string | null;
  reviewer_user_id?: number | null;
  reviewer_user_label?: string | null;
  status: string;
  reason?: string | null;
  submitted_at?: string | null;
  reviewed_at?: string | null;
  created_at: string;
  updated_at: string;
  items: Array<
    CustomerTagChangeItemPayload & {
      id: number;
      tag_name?: string | null;
      tag_code?: string | null;
      category_key?: string | null;
      group_code?: string | null;
      status: string;
      review_comment?: string | null;
    }
  >;
};

export type SalesOrderLinePayload = {
  product_code?: string | null;
  product_name: string;
  quantity: number;
  unit?: string | null;
  remark?: string | null;
};

export type SalesOrderRow = {
  id: number;
  order_no: string;
  external_order_no?: string | null;
  customer_code: string;
  customer_name_snapshot: string;
  source: string;
  status: string;
  planned_delivery_at?: string | null;
  delivery_address?: string | null;
  temporary_requirements_json?: Array<Record<string, unknown>> | null;
  requirement_snapshot_version: number;
  confirmed_at?: string | null;
  completed_at?: string | null;
  cancelled_at?: string | null;
  lines: Array<SalesOrderLinePayload & { id: number; line_no: number }>;
  requirements: Array<{
    id: number;
    tag_name: string;
    group_code?: string | null;
    source_type: string;
    requirement_json?: Record<string, unknown> | null;
  }>;
  delivery_id?: number | null;
  requirement_diff?: {
    added: Array<Record<string, unknown>>;
    removed: Array<Record<string, unknown>>;
    changed: Array<Record<string, unknown>>;
  } | null;
};

export type SalesOrderImportResult = {
  imported_orders: number;
  imported_lines: number;
  errors: Array<{ external_order_no?: string; message: string }>;
};

export type DeliveryAttachmentRow = {
  id: number;
  delivery_id: number;
  file_name: string;
  content_type?: string | null;
  size_bytes?: number | null;
  created_by_user_id?: number | null;
  created_at: string;
};

export type DeliveryTaskRow = {
  id: number;
  delivery_no: string;
  order_id: number;
  order_no?: string | null;
  customer_code?: string | null;
  customer_name?: string | null;
  status: string;
  planned_at?: string | null;
  delivery_address?: string | null;
  requirements_json?: Array<Record<string, unknown>> | null;
  assignee_user_id?: number | null;
  signed_by?: string | null;
  signed_at?: string | null;
  exception_note?: string | null;
  events: Array<Record<string, unknown>>;
  attachments: DeliveryAttachmentRow[];
};

export type CustomerTagHistory = {
  profile: CustomerTagProfile;
  requests: CustomerTagChangeRequest[];
};

export type CustomerBusinessProduct = {
  id: number;
  customer_code: string;
  product_category?: string | null;
  spec?: string | null;
  common_brand?: string | null;
  monthly_usage?: string | null;
  price_sensitivity?: string | null;
  cooperation_status?: string | null;
  change_type?: string | null;
  opportunity_note?: string | null;
  last_confirmed_at?: string | null;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type CustomerBusinessProfile = {
  id: number;
  customer_code: string;
  customer_name_snapshot: string;
  business_customer_type?: string | null;
  confirmed_at?: string | null;
  filled_by?: string | null;
  update_source?: string | null;
  update_type?: string | null;
  current_salesperson?: string | null;
  sales_channels?: string[] | null;
  business_status_tags?: string[] | null;
  business_status_label?: string | null;
  business_status_note?: string | null;
  other_status_label?: string | null;
  other_status_note?: string | null;
  latest_update_note?: string | null;
  version_no: number;
  confirmed_by?: string | null;
  created_by_user_id?: number | null;
  updated_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type CustomerBusinessProfileHistory = {
  id: number;
  customer_code: string;
  version_no: number;
  update_source?: string | null;
  update_type?: string | null;
  filled_by?: string | null;
  update_note?: string | null;
  confirmed_by?: string | null;
  snapshot_json?: Record<string, unknown> | null;
  created_by_user_id?: number | null;
  created_at: string;
};

export type CustomerCurrentSalesProduct = {
  product_code?: string | null;
  product_name?: string | null;
  monthly_sales_qty: string | number;
  quarter_sales_qty: string | number;
};

export type CustomerBusinessProfileResponse = {
  customer: MasterRow;
  profile: CustomerBusinessProfile | null;
  products: CustomerBusinessProduct[];
  history_summary: CustomerBusinessProfileHistory[];
  current_sales_products: CustomerCurrentSalesProduct[];
};

export type CustomerBusinessProductPayload = {
  id?: number | null;
  product_category?: string | null;
  spec?: string | null;
  common_brand?: string | null;
  monthly_usage?: string | null;
  price_sensitivity?: string | null;
  cooperation_status?: string | null;
  change_type?: string | null;
  opportunity_note?: string | null;
  last_confirmed_at?: string | null;
  sort_order?: number;
  is_active?: boolean;
};

export type CustomerRecommendedProductPayload = {
  product_name?: string | null;
  spec?: string | null;
  recommended_quote?: string | null;
  recommend_reason?: string | null;
  customer_feedback?: string | null;
  next_action?: string | null;
};

export type CustomerBusinessProfilePayload = {
  business_customer_type?: string | null;
  confirmed_at?: string | null;
  filled_by?: string | null;
  update_source?: string | null;
  update_type?: string | null;
  current_salesperson?: string | null;
  sales_channels?: string[];
  business_status_tags?: string[];
  business_status_label?: string | null;
  business_status_note?: string | null;
  other_status_label?: string | null;
  other_status_note?: string | null;
  latest_update_note?: string | null;
  confirmed_by?: string | null;
  products?: CustomerBusinessProductPayload[];
  recommended_products?: CustomerRecommendedProductPayload[];
};

export type EmployeeUpdatePayload = {
  employee_name?: string | null;
  user_id?: number | null;
  department?: string | null;
  position?: string | null;
  role_code?: string | null;
  manager_employee_code?: string | null;
  status?: string | null;
  phone?: string | null;
};

export type ProductUpdatePayload = {
  product_name?: string | null;
  spec?: string | null;
  unit?: string | null;
  category?: string | null;
  brand?: string | null;
  barcode?: string | null;
  reference_sale_price?: string | number | null;
  reference_cost?: string | number | null;
  status?: string | null;
};

export type ProductCreatePayload = ProductUpdatePayload & {
  product_code: string;
  product_name: string;
};

export type SupplierUpdatePayload = {
  supplier_name?: string | null;
  supplier_short_name?: string | null;
  supplier_type?: string | null;
  region?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  address?: string | null;
  status?: string | null;
};

export type SupplierCreatePayload = SupplierUpdatePayload & {
  supplier_code: string;
  supplier_name: string;
};

export type RoleRow = {
  id: number;
  role_code: string;
  role_name: string;
  description?: string | null;
  is_system_role: boolean;
};

export type RolePermissions = {
  role: RoleRow;
  permission_codes: string[];
};

export type RoleCreatePayload = {
  role_code: string;
  role_name: string;
  description?: string | null;
  permission_codes?: string[];
};

export type UserPermissions = {
  user: UserPublic;
  role_permission_codes: string[];
  allow_permission_codes: string[];
  deny_permission_codes: string[];
  final_permission_codes: string[];
};

export type UserPermissionOverride = {
  permission_code: string;
  effect: "allow" | "deny";
};

export type PermissionRow = {
  id: number;
  permission_code: string;
  permission_name: string;
  resource_type: string;
  action_type: string;
  description?: string | null;
};

export type AuthorityRule = {
  id: number;
  rule_code: string;
  rule_name: string;
  resource_type: string;
  action_type: string;
  allowed_roles: string[];
  requires_approval: boolean;
  is_active: boolean;
};

export type DataScopeRule = {
  id: number;
  subject_type: string;
  subject_id: string;
  resource_type: string;
  scope_mode: string;
  scope_value?: Record<string, unknown> | unknown[] | null;
  is_active: boolean;
};

export type FieldPermissionRule = {
  id: number;
  subject_type: string;
  subject_id: string;
  resource_type: string;
  field_name: string;
  permission_type: string;
  mask_rule?: string | null;
};

export type AuditLog = {
  id: number;
  user_id?: number | null;
  role_code?: string | null;
  action_type: string;
  resource_type: string;
  resource_id?: string | null;
  before_data?: Record<string, unknown> | unknown[] | null;
  after_data?: Record<string, unknown> | unknown[] | null;
  ip_address?: string | null;
  created_at: string;
};

export type ExternalApiPermissionFlags = {
  can_read_projects: boolean;
  can_read_customers: boolean;
  can_read_followups: boolean;
  can_read_judgements: boolean;
  can_read_tasks: boolean;
  can_read_approvals: boolean;
  can_read_audit_summary: boolean;
  can_read_products: boolean;
  can_read_suppliers: boolean;
  can_read_sales_summary: boolean;
  can_read_purchase_summary: boolean;
  can_read_inventory_summary: boolean;
  can_read_receivables: boolean;
  can_read_data_quality: boolean;
  can_read_changes: boolean;
  can_read_inventory_anomalies: boolean;
  can_read_inventory_evidence: boolean;
  can_read_sales_details_sensitive: boolean;
  can_read_purchase_details_sensitive: boolean;
  can_read_inventory_checks: boolean;
  can_read_imports: boolean;
  can_write_inventory_diagnoses: boolean;
  can_validate_inventory_actions: boolean;
  can_execute_inventory_rebuild: boolean;
  can_execute_inventory_upstream: boolean;
  can_read_inventory_action_status: boolean;
};

export type ExternalApiKeyRow = {
  id: number;
  key_id: string;
  name: string;
  owner_name?: string | null;
  key_prefix: string;
  scope_region?: string | null;
  scope_project_ids: number[];
  allowed_customer_fields: string[];
  allowed_ips: string[];
  permissions: ExternalApiPermissionFlags;
  permission_scopes: string[];
  rate_limit_per_minute: number;
  daily_request_limit: number;
  previous_key_prefix?: string | null;
  previous_key_expires_at?: string | null;
  rotated_at?: string | null;
  rotation_count: number;
  active: boolean;
  created_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
  expires_at?: string | null;
  last_used_at?: string | null;
  last_used_ip?: string | null;
  revoked_at?: string | null;
  revoked_reason?: string | null;
};

export type ExternalApiCatalog = {
  base_url: string;
  schema_version: string;
  openapi_url: string;
  customer_field_options: string[];
  default_customer_fields: string[];
  permission_options: Array<{
    code: keyof ExternalApiPermissionFlags;
    label: string;
  }>;
  endpoints: Array<{
    method: string;
    path: string;
    permission: string;
    description: string;
  }>;
};

export type ExternalApiKeyPayload = {
  name: string;
  owner_name?: string | null;
  scope_region?: string | null;
  scope_project_ids?: number[] | null;
  allowed_customer_fields: string[];
  allowed_ips?: string[] | null;
  expires_at?: string | null;
  rate_limit_per_minute: number;
  daily_request_limit: number;
} & ExternalApiPermissionFlags;

export type ExternalApiKeyCreateResult = {
  api_key: string;
  key: ExternalApiKeyRow;
};

export type ExternalApiUsageReport = {
  key_id: string;
  days: number;
  total: number;
  error_count: number;
  items: Array<{
    request_id: string;
    endpoint: string;
    method: string;
    status_code: number;
    duration_ms?: number | null;
    response_count?: number | null;
    client_ip?: string | null;
    created_at: string;
  }>;
};

export type ImportErrorRow = {
  id: number;
  batch_id: number;
  row_number: number;
  error_type: string;
  error_message: string;
  raw_row_json?: Record<string, unknown> | null;
  created_at: string;
};

export type MasterLinkIssue = {
  id: number;
  batch_id?: number | null;
  source_file_type: string;
  issue_type: string;
  expected_master_kind: string;
  reference_code?: string | null;
  reference_name?: string | null;
  counterpart_master_kind?: string | null;
  counterpart_code?: string | null;
  counterpart_name?: string | null;
  first_seen_date?: string | null;
  last_seen_date?: string | null;
  affected_rows: number;
  affected_documents: number;
  amount_total?: string | number | null;
  quantity_total?: string | number | null;
  status: string;
  resolution_type?: string | null;
  resolved_by_user_id?: number | null;
  resolved_at?: string | null;
  resolution_note?: string | null;
  source_json?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type MasterLinkIssuePage = {
  items: MasterLinkIssue[];
  total: number;
  limit: number;
  offset: number;
  summary: Record<string, number>;
};

export type MasterLinkIssueQuery = {
  issue_type?: string;
  expected_master_kind?: string;
  source_file_type?: string;
  status?: string;
  q?: string;
  limit?: number;
  offset?: number;
};

export type DataQualityRiskAlert = {
  rule_code: string;
  rule_name: string;
  rule_description: string;
  status: string;
  status_label: string;
  closure_hint?: string | null;
  is_actionable: boolean;
  level: "warning" | "risk" | string;
  category: string;
  resource_type?: string | null;
  code?: string | null;
  name?: string | null;
  reason: string;
  action?: string | null;
  affected_rows: number;
  affected_documents: number;
  affected_amount?: string | null;
  affected_quantity?: string | null;
  first_seen_date?: string | null;
  last_seen_date?: string | null;
  source?: string | null;
  metadata?: Record<string, unknown> | null;
};

export type DataQualityRiskSummary = {
  warning_count: number;
  risk_count: number;
  total: number;
  categories: Record<string, number>;
  rules: Record<string, number>;
};

export type DataQualityRiskAlertPage = {
  items: DataQualityRiskAlert[];
  total: number;
  limit: number;
  offset: number;
  summary: DataQualityRiskSummary;
};

export type DataQualityRiskRule = {
  rule_code: string;
  rule_name: string;
  level: "warning" | "risk" | string;
  category: string;
  resource_type?: string | null;
  scope: string;
  description: string;
  action: string;
  is_enabled: boolean;
};

export type DataQualityRiskRulePage = {
  items: DataQualityRiskRule[];
  total: number;
};

export type DataQualityRiskAlertQuery = {
  level?: string;
  category?: string;
  limit?: number;
  offset?: number;
};

export type DataQualityRiskRuleQuery = {
  level?: string;
  category?: string;
  resource_type?: string;
};

export type UserStatusHistory = {
  id: number;
  user_id: number;
  old_status?: string | null;
  new_status: string;
  reason?: string | null;
  changed_by?: number | null;
  changed_at: string;
};

const TOKEN_KEY = "project_base_token";
const API_ERROR_GET_DEDUP_MS = 5 * 60 * 1000;
const apiErrorGetLastSeen = new Map<string, number>();
let authExpiredPublished = false;

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
  authExpiredPublished = false;
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

function apiErrorPayload(rawBody: string): ApiErrorPayload {
  const rawMessage = rawBody.trim();
  if (!rawMessage) return {};
  try {
    const parsed = JSON.parse(rawMessage) as Record<string, unknown>;
    const detail = parsed.detail;
    const source = detail && typeof detail === "object"
      ? { ...parsed, ...(detail as Record<string, unknown>) }
      : parsed;
    const messageValue = typeof detail === "string" ? detail : source.message;
    return {
      error_code: typeof source.error_code === "string" ? source.error_code : null,
      message: typeof messageValue === "string" ? messageValue.trim() : null,
      request_id: typeof source.request_id === "string" ? source.request_id : null,
      module: typeof source.module === "string" ? source.module : null,
      resource_type: typeof source.resource_type === "string" ? source.resource_type : null,
      resource_id: typeof source.resource_id === "string" || typeof source.resource_id === "number" ? String(source.resource_id) : null,
      case_no: typeof source.case_no === "string" ? source.case_no : null,
      retryable: typeof source.retryable === "boolean" ? source.retryable : null,
      action_path: typeof source.action_path === "string" ? source.action_path : null,
      field_errors: Array.isArray(source.field_errors)
        ? source.field_errors.flatMap((item) => {
            if (!item || typeof item !== "object") return [];
            const fieldError = item as Record<string, unknown>;
            const field = typeof fieldError.field === "string" ? fieldError.field : null;
            const message = typeof fieldError.message === "string" ? fieldError.message : null;
            return field || message ? [{ field, message }] : [];
          })
        : [],
    };
  } catch {
    return { message: rawMessage };
  }
}

export function apiErrorMessage(status: number, rawBody: string) {
  const payload = apiErrorPayload(rawBody);
  const message = payload.message?.trim() || "";
  if (status >= 500 || /^internal server error$/i.test(message)) {
    return "服务器暂时不可用，请稍后重试。";
  }
  if (message === "Blocking CRM lead duplicate") {
    return "联系电话与现有线索完全一致，不能重复创建。";
  }
  if (message === "CRM lead duplicate acknowledgement required") {
    return "发现同名或相似线索，请核实并勾选确认后再保存。";
  }
  return message || `请求失败（${status}）`;
}

function createApiError(status: number, rawBody: string, requestId?: string | null) {
  const payload = apiErrorPayload(rawBody);
  if (!payload.request_id && requestId) payload.request_id = requestId;
  return new ApiError(status, apiErrorMessage(status, rawBody), payload);
}

function apiRequestPath(url: string) {
  try {
    return new URL(url, window.location.origin).pathname;
  } catch {
    return "/api";
  }
}

function publishApiError(error: ApiError, url: string, options: RequestInit) {
  if (typeof window === "undefined" || error.status === 401) return;
  const path = apiRequestPath(url);
  if (path.startsWith("/api/v1/auth/")) return;
  const method = String(options.method ?? "GET").toUpperCase();
  if (method === "GET") {
    const fingerprint = [path, error.status, error.error_code ?? "", error.message].join(":");
    const now = Date.now();
    const lastSeen = apiErrorGetLastSeen.get(fingerprint) ?? 0;
    if (now - lastSeen < API_ERROR_GET_DEDUP_MS) return;
    apiErrorGetLastSeen.set(fingerprint, now);
  }
  window.dispatchEvent(new CustomEvent<ApiErrorEventDetail>(API_ERROR_EVENT, {
    detail: { error, method, path }
  }));
}

function publishAuthExpired(url: string) {
  if (typeof window === "undefined") return;
  const path = apiRequestPath(url);
  if (path === "/api/v1/auth/login" || authExpiredPublished) return;
  authExpiredPublished = true;
  clearToken();
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
}

export async function requestJson<T>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type") &&
    options.body
  ) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const text = await response.text();
    const error = createApiError(response.status, text, response.headers.get("X-Request-ID"));
    if (response.status === 401) publishAuthExpired(url);
    publishApiError(error, url, options);
    throw error;
  }
  return response.json() as Promise<T>;
}

export async function login(username: string, password: string) {
  const data = await requestJson<{ access_token: string; user: UserPublic }>(
    "/api/v1/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ username, password }),
    },
  );
  setToken(data.access_token);
  return data.user;
}

export async function logout() {
  clearToken();
  await fetch("/api/v1/auth/logout", {
    method: "POST",
    credentials: "include",
  });
}

export function me() {
  return requestJson<UserPublic>("/api/v1/auth/me");
}

export function myPermissions() {
  return requestJson<string[]>("/api/v1/auth/my-permissions");
}

export function summary() {
  return requestJson<Summary>("/api/v1/admin/stage1/summary");
}

export function mobileOperationsOverview(days = 7) {
  return requestJson<MobileOperationsOverview>(
    `/api/v1/mobile/admin/operations/overview?days=${days}`,
  );
}

export function mobileAdminDevices() {
  return requestJson<MobileAdminDevicePage>(
    "/api/v1/mobile/admin/devices?limit=50",
  );
}

export function revokeMobileAdminDevice(sessionId: number) {
  return requestJson<{ status: string; session_id: number }>(
    `/api/v1/mobile/admin/devices/${sessionId}`,
    { method: "DELETE" },
  );
}

export function mobileAdminFeedback(status?: string) {
  const params = new URLSearchParams({ limit: "100" });
  if (status) params.set("status", status);
  return requestJson<MobileFeedbackPage>(
    `/api/v1/mobile/admin/feedback?${params}`,
  );
}

export function updateMobileAdminFeedback(
  id: number,
  status: MobileFeedbackRow["status"],
  resolution?: string,
) {
  return requestJson<MobileFeedbackRow>(`/api/v1/mobile/admin/feedback/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status, resolution: resolution || null }),
  });
}

export function mobileAdoptionOverview(days = 7) {
  return requestJson<MobileAdoptionOverview>(
    `/api/v1/mobile/admin/adoption/overview?days=${days}`,
  );
}

export async function mobileFeedbackAttachment(id: number) {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`/api/v1/mobile/feedback/${id}/attachment`, {
    headers,
    credentials: "include",
  });
  if (!response.ok)
    throw new Error(apiErrorMessage(response.status, await response.text()));
  return response.blob();
}

export function dashboardOverview(range: DashboardRange = "7d") {
  const params = new URLSearchParams({ range });
  return requestJson<DashboardOverview>(`/api/v1/dashboard/overview?${params}`);
}

export function batches(query: ImportBatchQuery = {}) {
  const params = new URLSearchParams();
  if (query.file_type) params.set("file_type", query.file_type);
  if (query.data_date_from) params.set("data_date_from", query.data_date_from);
  if (query.data_date_to) params.set("data_date_to", query.data_date_to);
  if (query.limit) params.set("limit", String(query.limit));
  return requestJson<ImportBatch[]>(
    `/api/v1/import/batches${params.toString() ? `?${params}` : ""}`,
  );
}

export function dataCalendarRules() {
  return requestJson<DataCalendarRuleRow[]>("/api/v1/import/calendar-rules");
}

export function dataCalendarCoverage(query: {
  data_date_from: string;
  data_date_to: string;
}) {
  const params = new URLSearchParams();
  params.set("data_date_from", query.data_date_from);
  params.set("data_date_to", query.data_date_to);
  return requestJson<DataCalendarCoverageRow[]>(
    `/api/v1/import/calendar-coverage?${params}`,
  );
}

export function saveDataCalendarRules(payload: DataCalendarRulePayload[]) {
  return requestJson<DataCalendarRuleRow[]>("/api/v1/import/calendar-rules", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function resetDataCalendarRules() {
  return requestJson<DataCalendarRuleRow[]>(
    "/api/v1/import/calendar-rules/reset",
    { method: "POST" },
  );
}

export function sendDataCalendarReminder(payload: DataCalendarReminderRequest) {
  return requestJson<DataCalendarReminderResponse>(
    "/api/v1/import/calendar-reminders",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function importErrors(batchId: number) {
  return requestJson<ImportErrorRow[]>(
    `/api/v1/import/batches/${batchId}/errors`,
  );
}

export function batchMasterLinkIssues(batchId: number) {
  return requestJson<MasterLinkIssue[]>(
    `/api/v1/import/batches/${batchId}/master-link-issues`,
  );
}

export function masterLinkIssues(query: MasterLinkIssueQuery = {}) {
  const params = new URLSearchParams();
  if (query.issue_type) params.set("issue_type", query.issue_type);
  if (query.expected_master_kind)
    params.set("expected_master_kind", query.expected_master_kind);
  if (query.source_file_type)
    params.set("source_file_type", query.source_file_type);
  if (query.status) params.set("status", query.status);
  if (query.q) params.set("q", query.q);
  if (query.limit) params.set("limit", String(query.limit));
  if (query.offset) params.set("offset", String(query.offset));
  return requestJson<MasterLinkIssuePage>(
    `/api/v1/data-quality/master-link/issues${params.toString() ? `?${params}` : ""}`,
  );
}

export function rebuildMasterLinkIssues(batchId?: number) {
  const params = new URLSearchParams();
  if (batchId) params.set("batch_id", String(batchId));
  return requestJson<{ batches: number; issues: number }>(
    `/api/v1/data-quality/master-link/rebuild${params.toString() ? `?${params}` : ""}`,
    {
      method: "POST",
    },
  );
}

export function resolveMasterLinkIssue(
  issueId: number,
  payload: { resolution_type?: string; note?: string | null } = {},
) {
  return requestJson<MasterLinkIssue>(
    `/api/v1/data-quality/master-link/issues/${issueId}/resolve`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function dataQualityRiskAlerts(query: DataQualityRiskAlertQuery = {}) {
  const params = new URLSearchParams();
  if (query.level) params.set("level", query.level);
  if (query.category) params.set("category", query.category);
  if (query.limit) params.set("limit", String(query.limit));
  if (query.offset) params.set("offset", String(query.offset));
  return requestJson<DataQualityRiskAlertPage>(
    `/api/v1/data-quality/risk-alerts${params.toString() ? `?${params}` : ""}`,
  );
}

export function dataQualityRiskRules(query: DataQualityRiskRuleQuery = {}) {
  const params = new URLSearchParams();
  if (query.level) params.set("level", query.level);
  if (query.category) params.set("category", query.category);
  if (query.resource_type) params.set("resource_type", query.resource_type);
  return requestJson<DataQualityRiskRulePage>(
    `/api/v1/data-quality/risk-rules${params.toString() ? `?${params}` : ""}`,
  );
}

export function uploadImport(formData: FormData) {
  return requestJson<ImportBatch>("/api/v1/import/upload", {
    method: "POST",
    body: formData,
  });
}

export function validateImport(batchId: number) {
  return requestJson<ImportBatch>(
    `/api/v1/import/batches/${batchId}/validate`,
    { method: "POST" },
  );
}

export function commitImport(batchId: number) {
  return requestJson<ImportBatch>(`/api/v1/import/batches/${batchId}/commit`, {
    method: "POST",
  });
}

export function imageProcessingConfig() {
  return requestJson<ImageProcessingConfig>("/api/v1/image-jobs/config");
}

export function imageProcessingJobs(limit = 20) {
  const params = new URLSearchParams({ limit: String(limit) });
  return requestJson<ImageProcessingJob[]>(`/api/v1/image-jobs?${params}`);
}

export function createImageProcessingJob(formData: FormData) {
  return requestJson<ImageProcessingJobCreateResult>("/api/v1/image-jobs", {
    method: "POST",
    body: formData,
  });
}

export function imageProcessingJob(jobId: number) {
  return requestJson<ImageProcessingJobDetail>(`/api/v1/image-jobs/${jobId}`);
}

export function externalApiCatalog() {
  return requestJson<ExternalApiCatalog>("/api/v1/external-api/catalog");
}

export function externalApiKeys() {
  return requestJson<ExternalApiKeyRow[]>("/api/v1/external-api/keys");
}

export function createExternalApiKey(payload: ExternalApiKeyPayload) {
  return requestJson<ExternalApiKeyCreateResult>("/api/v1/external-api/keys", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function disableExternalApiKey(keyId: string) {
  return requestJson<ExternalApiKeyRow>(
    `/api/v1/external-api/keys/${keyId}/disable`,
    { method: "POST" },
  );
}

export function enableExternalApiKey(keyId: string) {
  return requestJson<ExternalApiKeyRow>(
    `/api/v1/external-api/keys/${keyId}/enable`,
    { method: "POST" },
  );
}

export function revokeExternalApiKey(keyId: string, reason = "manual_revoke") {
  return requestJson<ExternalApiKeyRow>(
    `/api/v1/external-api/keys/${keyId}/revoke`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
  );
}

export function rotateExternalApiKey(keyId: string, graceMinutes = 15) {
  return requestJson<ExternalApiKeyCreateResult>(
    `/api/v1/external-api/keys/${keyId}/rotate`,
    {
      method: "POST",
      body: JSON.stringify({ grace_minutes: graceMinutes }),
    },
  );
}

export function updateExternalApiKeyCustomerFields(
  keyId: string,
  allowedCustomerFields: string[],
) {
  return requestJson<ExternalApiKeyRow>(
    `/api/v1/external-api/keys/${keyId}/customer-fields`,
    {
      method: "PATCH",
      body: JSON.stringify({ allowed_customer_fields: allowedCustomerFields }),
    },
  );
}

export function externalApiKeyUsage(keyId: string, days = 7, limit = 50) {
  const params = new URLSearchParams({
    days: String(days),
    limit: String(limit),
  });
  return requestJson<ExternalApiUsageReport>(
    `/api/v1/external-api/keys/${keyId}/usage?${params}`,
  );
}

export function masterData(kind: string, q = "") {
  const params = new URLSearchParams({ limit: "100" });
  if (q) params.set("q", q);
  return requestJson<MasterRow[]>(`/api/v1/master-data/${kind}?${params}`);
}

export function masterDataPage(
  kind: string,
  options: {
    q?: string;
    limit?: number;
    offset?: number;
    categoryPath?: string[];
    portraitScale?: string;
    portraitPaymentLevel?: string;
    portraitCategory?: string;
    portraitMargin?: string;
    portraitReturn?: string;
    portraitGrowth?: string;
    customerTags?: string[];
    customerTagMatch?: "any" | "all";
    assignmentScope?: string;
    missingPhone?: boolean;
    missingContact?: boolean;
    missingAddress?: boolean;
    missingGroup?: boolean;
    missingBusinessProfile?: boolean;
    missingBusinessProducts?: boolean;
    secondAssignmentCandidate?: boolean;
    attentionState?: string;
    attentionReason?: string;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.q) params.set("q", options.q);
  if (options.categoryPath && options.categoryPath.length > 0)
    params.set("category_path", JSON.stringify(options.categoryPath));
  if (options.portraitScale)
    params.set("portrait_scale", options.portraitScale);
  if (options.portraitPaymentLevel)
    params.set("portrait_payment_level", options.portraitPaymentLevel);
  if (options.portraitCategory)
    params.set("portrait_category", options.portraitCategory);
  if (options.portraitMargin)
    params.set("portrait_margin", options.portraitMargin);
  if (options.portraitReturn)
    params.set("portrait_return", options.portraitReturn);
  if (options.portraitGrowth)
    params.set("portrait_growth", options.portraitGrowth);
  if (options.customerTags && options.customerTags.length > 0)
    params.set("customer_tags", options.customerTags.join(","));
  if (options.customerTagMatch)
    params.set("customer_tag_match", options.customerTagMatch);
  if (options.assignmentScope)
    params.set("assignment_scope", options.assignmentScope);
  if (options.missingPhone) params.set("missing_phone", "true");
  if (options.missingContact) params.set("missing_contact", "true");
  if (options.missingAddress) params.set("missing_address", "true");
  if (options.missingGroup) params.set("missing_group", "true");
  if (options.missingBusinessProfile)
    params.set("missing_business_profile", "true");
  if (options.missingBusinessProducts)
    params.set("missing_business_products", "true");
  if (options.secondAssignmentCandidate)
    params.set("second_assignment_candidate", "true");
  if (options.attentionState)
    params.set("attention_state", options.attentionState);
  if (options.attentionReason)
    params.set("attention_reason", options.attentionReason);
  return requestJson<MasterPage>(`/api/v1/master-data/${kind}/page?${params}`);
}

export function masterHierarchy(kind: "customers" | "products") {
  return requestJson<MasterCategoryNode>(
    `/api/v1/master-data/${kind}/hierarchy`,
  );
}

export function masterCategoryNodes(
  kind: "customers" | "products" | "customer_groups",
  includeDisabled = true,
) {
  const params = new URLSearchParams({
    include_disabled: String(includeDisabled),
  });
  return requestJson<MasterCategoryNodeRow[]>(
    `/api/v1/master-data/categories/${kind}/nodes?${params}`,
  );
}

export function createMasterCategoryNode(
  kind: "customers" | "products" | "customer_groups",
  payload: MasterCategoryNodePayload,
) {
  return requestJson<MasterCategoryNodeRow>(
    `/api/v1/master-data/categories/${kind}/nodes`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function updateMasterCategoryNode(
  categoryId: number,
  payload: MasterCategoryNodePayload,
) {
  return requestJson<MasterCategoryNodeRow>(
    `/api/v1/master-data/categories/nodes/${categoryId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function deleteMasterCategoryNode(categoryId: number) {
  return requestJson<{
    status: string;
    deleted_category_ids: number[];
    deleted_bindings: number;
  }>(`/api/v1/master-data/categories/nodes/${categoryId}`, {
    method: "DELETE",
  });
}

export function bindMasterCategoryResource(
  categoryId: number,
  resourceCode: string,
  isPrimary = true,
) {
  return requestJson<MasterCategoryBindingRow>(
    `/api/v1/master-data/categories/nodes/${categoryId}/bindings`,
    {
      method: "POST",
      body: JSON.stringify({
        resource_code: resourceCode,
        is_primary: isPrimary,
        source: "manual",
      }),
    },
  );
}

export function unbindMasterCategoryResource(
  categoryId: number,
  resourceCode: string,
) {
  return requestJson<{
    status: string;
    resource_code: string;
    category_id: number;
  }>(
    `/api/v1/master-data/categories/nodes/${categoryId}/bindings/${encodeURIComponent(resourceCode)}`,
    {
      method: "DELETE",
    },
  );
}

export function resolveSettlementUnit(options: {
  code?: string | number | null;
  name?: string | number | null;
  arBalance?: string | number | null;
  apBalance?: string | number | null;
  advanceReceiptBalance?: string | number | null;
  advancePaymentBalance?: string | number | null;
}) {
  const params = new URLSearchParams();
  if (
    options.code !== null &&
    options.code !== undefined &&
    options.code !== ""
  )
    params.set("code", String(options.code));
  if (
    options.name !== null &&
    options.name !== undefined &&
    options.name !== ""
  )
    params.set("name", String(options.name));
  if (
    options.arBalance !== null &&
    options.arBalance !== undefined &&
    options.arBalance !== ""
  )
    params.set("ar_balance", String(options.arBalance));
  if (
    options.apBalance !== null &&
    options.apBalance !== undefined &&
    options.apBalance !== ""
  )
    params.set("ap_balance", String(options.apBalance));
  if (
    options.advanceReceiptBalance !== null &&
    options.advanceReceiptBalance !== undefined &&
    options.advanceReceiptBalance !== ""
  )
    params.set(
      "advance_receipt_balance",
      String(options.advanceReceiptBalance),
    );
  if (
    options.advancePaymentBalance !== null &&
    options.advancePaymentBalance !== undefined &&
    options.advancePaymentBalance !== ""
  )
    params.set(
      "advance_payment_balance",
      String(options.advancePaymentBalance),
    );
  return requestJson<SettlementUnitResolveResult>(
    `/api/v1/master-data/settlement-unit/resolve?${params}`,
  );
}

export function updateCustomer(
  customerCode: string,
  payload: CustomerUpdatePayload,
) {
  return requestJson<MasterRow>(
    `/api/v1/master-data/customers/${encodeURIComponent(customerCode)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function createCustomer(payload: CustomerCreatePayload) {
  return requestJson<MasterRow>("/api/v1/master-data/customers", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function customerBusinessProfile(customerCode: string) {
  return requestJson<CustomerBusinessProfileResponse>(
    `/api/v1/master-data/customers/${encodeURIComponent(customerCode)}/business-profile`,
  );
}

export function customerBusinessProfileHistory(
  customerCode: string,
  filters: { limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams({
    limit: String(filters.limit ?? 20),
    offset: String(filters.offset ?? 0),
  });
  return requestJson<CustomerBusinessProfileHistory[]>(
    `/api/v1/master-data/customers/${encodeURIComponent(customerCode)}/business-profile/history?${params}`,
  );
}

export function updateCustomerBusinessProfile(
  customerCode: string,
  payload: CustomerBusinessProfilePayload,
) {
  return requestJson<CustomerBusinessProfileResponse>(
    `/api/v1/master-data/customers/${encodeURIComponent(customerCode)}/business-profile`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export function crmLinkedCustomerBusinessProfile(customerCode: string) {
  return requestJson<CustomerBusinessProfileResponse>(
    `/api/v1/crm/linked-customers/${encodeURIComponent(customerCode)}/business-profile`,
  );
}

export function crmLinkedCustomerProfile(customerCode: string) {
  return requestJson<MasterRow>(
    `/api/v1/crm/linked-customers/${encodeURIComponent(customerCode)}/profile`,
  );
}

export function customerPortraitTags(customerCode: string) {
  return requestJson<CustomerPortraitTagsResult>(
    `/api/v1/master-data/customers/${encodeURIComponent(customerCode)}/portrait/tags`,
  );
}

export function refreshCustomerPortraitTags(customerCode: string) {
  return requestJson<CustomerPortraitTagsResult>(
    `/api/v1/master-data/customers/${encodeURIComponent(customerCode)}/portrait/tags/refresh`,
    {
      method: "POST",
    },
  );
}

export function updateProduct(
  productCode: string,
  payload: ProductUpdatePayload,
) {
  return requestJson<MasterRow>(
    `/api/v1/master-data/products/${encodeURIComponent(productCode)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function createProduct(payload: ProductCreatePayload) {
  return requestJson<MasterRow>("/api/v1/master-data/products", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateSupplier(
  supplierCode: string,
  payload: SupplierUpdatePayload,
) {
  return requestJson<MasterRow>(
    `/api/v1/master-data/suppliers/${encodeURIComponent(supplierCode)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function createSupplier(payload: SupplierCreatePayload) {
  return requestJson<MasterRow>("/api/v1/master-data/suppliers", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function employees(q = "") {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  return requestJson<MasterRow[]>(
    `/api/v1/employees${params.toString() ? `?${params}` : ""}`,
  );
}

export function employeesPage(
  options: { q?: string; limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.q) params.set("q", options.q);
  return requestJson<MasterPage>(`/api/v1/employees/page?${params}`);
}

export function salesDetailsPage(
  options: {
    q?: string;
    dateFrom?: string;
    dateTo?: string;
    customerCode?: string;
    productCode?: string;
    warehouseName?: string;
    employeeName?: string;
    categoryPath?: string[];
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.q) params.set("q", options.q);
  if (options.dateFrom) params.set("date_from", options.dateFrom);
  if (options.dateTo) params.set("date_to", options.dateTo);
  if (options.customerCode) params.set("customer_code", options.customerCode);
  if (options.productCode) params.set("product_code", options.productCode);
  if (options.warehouseName)
    params.set("warehouse_name", options.warehouseName);
  if (options.employeeName) params.set("employee_name", options.employeeName);
  if (options.categoryPath?.length)
    params.set("category_path", JSON.stringify(options.categoryPath));
  return requestJson<SalesDetailPage>(
    `/api/v1/process-data/sales-details/page?${params}`,
  );
}

export function salesDetail(salesDetailId: number) {
  return requestJson<SalesDetailRow>(
    `/api/v1/process-data/sales-details/${salesDetailId}`,
  );
}

export function salesDetailHierarchy() {
  return requestJson<ProcessCategoryNode>(
    "/api/v1/process-data/sales-details/hierarchy/tree",
  );
}

export function updateSalesDetail(
  salesDetailId: number,
  payload: Record<string, string | number | null>,
) {
  return requestJson<SalesDetailRow>(
    `/api/v1/process-data/sales-details/${salesDetailId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function inventorySnapshotsPage(
  options: {
    q?: string;
    dateFrom?: string;
    dateTo?: string;
    productCode?: string;
    defaultSupplier?: string;
    inventoryStatus?: string;
    warehouseName?: string;
    categoryPath?: string[];
    attentionState?: string;
    attentionReason?: string;
    snapshotScope?: "latest" | "daily_latest" | "all";
    batchId?: number;
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.q) params.set("q", options.q);
  if (options.dateFrom) params.set("date_from", options.dateFrom);
  if (options.dateTo) params.set("date_to", options.dateTo);
  if (options.productCode) params.set("product_code", options.productCode);
  if (options.defaultSupplier)
    params.set("default_supplier", options.defaultSupplier);
  if (options.inventoryStatus)
    params.set("inventory_status", options.inventoryStatus);
  if (options.warehouseName)
    params.set("warehouse_name", options.warehouseName);
  if (options.categoryPath?.length)
    params.set("category_path", JSON.stringify(options.categoryPath));
  if (options.attentionState)
    params.set("attention_state", options.attentionState);
  if (options.attentionReason)
    params.set("attention_reason", options.attentionReason);
  if (options.snapshotScope)
    params.set("snapshot_scope", options.snapshotScope);
  if (options.batchId) params.set("batch_id", String(options.batchId));
  return requestJson<InventorySnapshotPage>(
    `/api/v1/process-data/inventory-snapshots/page?${params}`,
  );
}

export function inventorySnapshot(snapshotId: number) {
  return requestJson<InventorySnapshotRow>(
    `/api/v1/process-data/inventory-snapshots/${snapshotId}`,
  );
}

export function inventorySnapshotHierarchy(
  options: {
    dateFrom?: string;
    dateTo?: string;
    snapshotScope?: "latest" | "daily_latest" | "all";
    batchId?: number;
  } = {},
) {
  const params = new URLSearchParams();
  if (options.dateFrom) params.set("date_from", options.dateFrom);
  if (options.dateTo) params.set("date_to", options.dateTo);
  if (options.snapshotScope)
    params.set("snapshot_scope", options.snapshotScope);
  if (options.batchId) params.set("batch_id", String(options.batchId));
  return requestJson<ProcessCategoryNode>(
    `/api/v1/process-data/inventory-snapshots/hierarchy/tree${params.size ? `?${params}` : ""}`,
  );
}

export function updateInventorySnapshot(
  snapshotId: number,
  payload: Record<string, string | number | null>,
) {
  return requestJson<InventorySnapshotRow>(
    `/api/v1/process-data/inventory-snapshots/${snapshotId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function uploadInventoryCheck(formData: FormData) {
  return requestJson<InventoryCheckBatch>("/api/v1/inventory-check/batches", {
    method: "POST",
    body: formData,
  });
}

export function inventoryCheckBatches(
  options: { limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 30),
    offset: String(options.offset ?? 0),
  });
  return requestJson<InventoryCheckBatchPage>(
    `/api/v1/inventory-check/batches?${params}`,
  );
}

export function inventoryCheckBatch(batchId: number) {
  return requestJson<InventoryCheckBatch>(
    `/api/v1/inventory-check/batches/${batchId}`,
  );
}

export function rebuildInventoryCheckBatch(batchId: number) {
  return requestJson<InventoryCheckBatch>(
    `/api/v1/inventory-check/batches/${batchId}/rebuild`,
    { method: "POST" },
  );
}

export function inventoryCheckResults(
  batchId: number,
  options: { type?: string; q?: string; limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.type) params.set("type", options.type);
  if (options.q) params.set("q", options.q);
  return requestJson<InventoryCheckResultPage>(
    `/api/v1/inventory-check/batches/${batchId}/results?${params}`,
  );
}

export function inventoryFlowPage(
  options: {
    q?: string;
    dateFrom?: string;
    dateTo?: string;
    warehouseName?: string;
    productCode?: string;
    anomalyType?: string;
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.q) params.set("q", options.q);
  if (options.dateFrom) params.set("date_from", options.dateFrom);
  if (options.dateTo) params.set("date_to", options.dateTo);
  if (options.warehouseName)
    params.set("warehouse_name", options.warehouseName);
  if (options.productCode) params.set("product_code", options.productCode);
  if (options.anomalyType) params.set("anomaly_type", options.anomalyType);
  return requestJson<InventoryFlowPage>(
    `/api/v1/inventory-flow/page?${params}`,
  );
}

export function salesInventoryStatus(ids: Array<string | number>) {
  const params = new URLSearchParams({ ids: ids.map(String).join(",") });
  return requestJson<{ items: Record<string, SalesInventoryStatus> }>(
    `/api/v1/inventory-flow/sales-status?${params}`,
  );
}

export function rebuildInventoryFlow() {
  return requestJson<{ created: number; trigger_batch_id: number }>(
    "/api/v1/inventory-flow/rebuild",
    { method: "POST" },
  );
}

export function inventoryCheckExportUrl(batchId: number) {
  return `/api/v1/inventory-check/batches/${batchId}/export`;
}

export async function downloadInventoryCheckResults(batchId: number) {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(inventoryCheckExportUrl(batchId), {
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(apiErrorMessage(response.status, text));
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename\\*=UTF-8''([^;]+)/);
  const filename = match
    ? decodeURIComponent(match[1])
    : `inventory-check-${batchId}.xlsx`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function purchaseDetailsPage(
  options: {
    q?: string;
    dateFrom?: string;
    dateTo?: string;
    supplierCode?: string;
    productCode?: string;
    warehouseName?: string;
    employeeName?: string;
    categoryPath?: string[];
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.q) params.set("q", options.q);
  if (options.dateFrom) params.set("date_from", options.dateFrom);
  if (options.dateTo) params.set("date_to", options.dateTo);
  if (options.supplierCode) params.set("supplier_code", options.supplierCode);
  if (options.productCode) params.set("product_code", options.productCode);
  if (options.warehouseName)
    params.set("warehouse_name", options.warehouseName);
  if (options.employeeName) params.set("employee_name", options.employeeName);
  if (options.categoryPath?.length)
    params.set("category_path", JSON.stringify(options.categoryPath));
  return requestJson<PurchaseDetailPage>(
    `/api/v1/process-data/purchase-details/page?${params}`,
  );
}

export function purchaseDetail(purchaseDetailId: number) {
  return requestJson<PurchaseDetailRow>(
    `/api/v1/process-data/purchase-details/${purchaseDetailId}`,
  );
}

export function purchaseDetailHierarchy() {
  return requestJson<ProcessCategoryNode>(
    "/api/v1/process-data/purchase-details/hierarchy/tree",
  );
}

export function updatePurchaseDetail(
  purchaseDetailId: number,
  payload: Record<string, string | number | null>,
) {
  return requestJson<PurchaseDetailRow>(
    `/api/v1/process-data/purchase-details/${purchaseDetailId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function accountBalancesPage(
  options: {
    q?: string;
    dateFrom?: string;
    dateTo?: string;
    settlementUnitCode?: string;
    settlementUnitName?: string;
    balanceType?: string;
    categoryPath?: string[];
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.q) params.set("q", options.q);
  if (options.dateFrom) params.set("date_from", options.dateFrom);
  if (options.dateTo) params.set("date_to", options.dateTo);
  if (options.settlementUnitCode)
    params.set("settlement_unit_code", options.settlementUnitCode);
  if (options.settlementUnitName)
    params.set("settlement_unit_name", options.settlementUnitName);
  if (options.balanceType) params.set("balance_type", options.balanceType);
  if (options.categoryPath?.length)
    params.set("category_path", JSON.stringify(options.categoryPath));
  return requestJson<AccountBalancePage>(
    `/api/v1/process-data/account-balances/page?${params}`,
  );
}

export function accountBalance(balanceId: number) {
  return requestJson<AccountBalanceRow>(
    `/api/v1/process-data/account-balances/${balanceId}`,
  );
}

export function accountBalanceHierarchy() {
  return requestJson<ProcessCategoryNode>(
    "/api/v1/process-data/account-balances/hierarchy/tree",
  );
}

export function updateAccountBalance(
  balanceId: number,
  payload: Record<string, string | number | null>,
) {
  return requestJson<AccountBalanceRow>(
    `/api/v1/process-data/account-balances/${balanceId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function accountLedgerPage(
  options: {
    q?: string;
    dateFrom?: string;
    dateTo?: string;
    settlementUnitCode?: string;
    settlementUnitName?: string;
    documentType?: string;
    rowRole?: string;
    categoryPath?: string[];
    attentionState?: string;
    attentionReason?: string;
    snapshotScope?: "latest" | "daily_latest" | "all";
    batchId?: number;
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.q) params.set("q", options.q);
  if (options.dateFrom) params.set("date_from", options.dateFrom);
  if (options.dateTo) params.set("date_to", options.dateTo);
  if (options.settlementUnitCode)
    params.set("settlement_unit_code", options.settlementUnitCode);
  if (options.settlementUnitName)
    params.set("settlement_unit_name", options.settlementUnitName);
  if (options.documentType) params.set("document_type", options.documentType);
  if (options.rowRole) params.set("row_role", options.rowRole);
  if (options.categoryPath?.length)
    params.set("category_path", JSON.stringify(options.categoryPath));
  if (options.attentionState)
    params.set("attention_state", options.attentionState);
  if (options.attentionReason)
    params.set("attention_reason", options.attentionReason);
  if (options.snapshotScope)
    params.set("snapshot_scope", options.snapshotScope);
  if (options.batchId) params.set("batch_id", String(options.batchId));
  return requestJson<AccountLedgerPage>(
    `/api/v1/process-data/account-ledger/page?${params}`,
  );
}

export function accountLedgerEntry(entryId: number) {
  return requestJson<AccountLedgerRow>(
    `/api/v1/process-data/account-ledger/${entryId}`,
  );
}

export function accountLedgerHierarchy(
  options: {
    dateFrom?: string;
    dateTo?: string;
    rowRole?: string;
    snapshotScope?: "latest" | "daily_latest" | "all";
    batchId?: number;
  } = {},
) {
  const params = new URLSearchParams();
  if (options.dateFrom) params.set("date_from", options.dateFrom);
  if (options.dateTo) params.set("date_to", options.dateTo);
  if (options.rowRole) params.set("row_role", options.rowRole);
  if (options.snapshotScope)
    params.set("snapshot_scope", options.snapshotScope);
  if (options.batchId) params.set("batch_id", String(options.batchId));
  return requestJson<ProcessCategoryNode>(
    `/api/v1/process-data/account-ledger/hierarchy/tree${params.size ? `?${params}` : ""}`,
  );
}

export function customerTags(includeInactive = false) {
  const params = new URLSearchParams({
    include_inactive: String(includeInactive),
  });
  return requestJson<CustomerTagRow[]>(
    `/api/v1/master-data/customer-tags?${params}`,
  );
}

export function createCustomerTag(payload: CustomerTagPayload) {
  return requestJson<CustomerTagRow>("/api/v1/master-data/customer-tags", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateCustomerTag(
  tagId: number,
  payload: CustomerTagUpdatePayload,
) {
  return requestJson<CustomerTagRow>(
    `/api/v1/master-data/customer-tags/${tagId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function structuredCustomerTagCatalog(
  options: {
    categoryKey?: string;
    groupCode?: string;
    includeInactive?: boolean;
    includeLegacy?: boolean;
  } = {},
) {
  const params = new URLSearchParams();
  if (options.categoryKey) params.set("category_key", options.categoryKey);
  if (options.groupCode) params.set("group_code", options.groupCode);
  if (options.includeInactive) params.set("include_inactive", "true");
  if (options.includeLegacy) params.set("include_legacy", "true");
  return requestJson<StructuredCustomerTag[]>(
    `/api/v1/customer-tagging/catalog${params.size ? `?${params}` : ""}`,
  );
}

export function customerTagCatalogVersions() {
  return requestJson<CustomerTagCatalogVersion[]>(
    "/api/v1/customer-tagging/catalog/versions",
  );
}

export function createCustomerTagCatalogVersion(payload: {
  version_code: string;
  name: string;
  description?: string | null;
}) {
  return requestJson<CustomerTagCatalogVersion>(
    "/api/v1/customer-tagging/catalog/versions",
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function customerTagCatalogVersionDefinitions(versionId: number) {
  return requestJson<StructuredCustomerTag[]>(
    `/api/v1/customer-tagging/catalog/versions/${versionId}/tags`,
  );
}

export function createCustomerTagCatalogDefinition(
  versionId: number,
  payload: CustomerTagCatalogDefinitionPayload,
) {
  return requestJson<StructuredCustomerTag>(
    `/api/v1/customer-tagging/catalog/versions/${versionId}/tags`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function replaceCustomerTagCatalogDefinition(
  tagId: number,
  replacementTagId: number,
) {
  return requestJson<StructuredCustomerTag>(
    `/api/v1/customer-tagging/catalog/tags/${tagId}/replacement`,
    {
      method: "POST",
      body: JSON.stringify({ replacement_tag_id: replacementTagId }),
    },
  );
}

export function activateCustomerTagCatalogVersion(versionId: number) {
  return requestJson<CustomerTagCatalogVersion>(
    `/api/v1/customer-tagging/catalog/versions/${versionId}/activate`,
    { method: "POST" },
  );
}

export function customerTagGovernanceSettings() {
  return requestJson<CustomerTagGovernanceSettings>(
    "/api/v1/customer-tagging/settings",
  );
}

export function customerTagRuleVersions() {
  return requestJson<CustomerTagRuleVersion[]>(
    "/api/v1/customer-tagging/rules",
  );
}

export function createCustomerTagRuleVersion(payload: {
  rule_code: string;
  name: string;
  parameters_json: Record<string, number>;
}) {
  return requestJson<CustomerTagRuleVersion>("/api/v1/customer-tagging/rules", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function activateCustomerTagRuleVersion(ruleId: number) {
  return requestJson<CustomerTagRuleVersion>(
    `/api/v1/customer-tagging/rules/${ruleId}/activate`,
    { method: "POST" },
  );
}

export function generateCustomerTagRecommendations(customerCode?: string) {
  const params = new URLSearchParams();
  if (customerCode) params.set("customer_code", customerCode);
  return requestJson<CustomerTagRecommendation[]>(
    `/api/v1/customer-tagging/recommendations/generate${params.size ? `?${params}` : ""}`,
    { method: "POST" },
  );
}

export function customerTagRecommendations(
  options: { customerCode?: string; status?: string } = {},
) {
  const params = new URLSearchParams();
  if (options.customerCode) params.set("customer_code", options.customerCode);
  if (options.status !== undefined) params.set("status_value", options.status);
  return requestJson<CustomerTagRecommendation[]>(
    `/api/v1/customer-tagging/recommendations${params.size ? `?${params}` : ""}`,
  );
}

export function decideCustomerTagRecommendation(
  recommendationId: number,
  payload: {
    decision: "accept" | "reject";
    manual_result?: string | null;
    manual_note: string;
    reviewer_user_id?: number | null;
  },
) {
  return requestJson<CustomerTagChangeRequest | CustomerTagRecommendation>(
    `/api/v1/customer-tagging/recommendations/${recommendationId}/decision`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function updateCustomerTagGovernanceSettings(
  payload: Partial<CustomerTagGovernanceSettings>,
) {
  return requestJson<CustomerTagGovernanceSettings>(
    "/api/v1/customer-tagging/settings",
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function structuredCustomerTagProfile(
  customerCode: string,
  includeHistory = false,
) {
  const params = new URLSearchParams({
    include_history: String(includeHistory),
  });
  return requestJson<CustomerTagProfile>(
    `/api/v1/customer-tagging/customers/${encodeURIComponent(customerCode)}/profile?${params}`,
  );
}

export function customerTagHistory(customerCode: string) {
  return requestJson<CustomerTagHistory>(
    `/api/v1/customer-tagging/customers/${encodeURIComponent(customerCode)}/history`,
  );
}

export function structuredTaggedCustomers(
  options: {
    q?: string;
    categoryKey?: string;
    groupCode?: string;
    tagIds?: number[];
    assignmentStatus?: string;
    ownerUserId?: number;
    reviewDateFrom?: string;
    reviewDateTo?: string;
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.q) params.set("q", options.q);
  if (options.categoryKey) params.set("category_key", options.categoryKey);
  if (options.groupCode) params.set("group_code", options.groupCode);
  if (options.tagIds?.length) params.set("tag_ids", options.tagIds.join(","));
  if (options.assignmentStatus)
    params.set("assignment_status", options.assignmentStatus);
  if (options.ownerUserId)
    params.set("owner_user_id", String(options.ownerUserId));
  if (options.reviewDateFrom)
    params.set("review_date_from", options.reviewDateFrom);
  if (options.reviewDateTo) params.set("review_date_to", options.reviewDateTo);
  return requestJson<{
    items: TaggedCustomerRow[];
    total: number;
    limit: number;
    offset: number;
  }>(`/api/v1/customer-tagging/customers?${params}`);
}

export function customerTagChangeRequests(
  options: {
    status?: string;
    customerCode?: string;
    mine?: boolean;
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.status) params.set("status_value", options.status);
  if (options.customerCode) params.set("customer_code", options.customerCode);
  if (options.mine) params.set("mine", "true");
  return requestJson<{
    items: CustomerTagChangeRequest[];
    total: number;
    limit: number;
    offset: number;
  }>(`/api/v1/customer-tagging/requests?${params}`);
}

export function createCustomerTagChangeRequest(payload: {
  customer_code: string;
  reason?: string;
  reviewer_user_id?: number;
  items: CustomerTagChangeItemPayload[];
}) {
  return requestJson<CustomerTagChangeRequest>(
    "/api/v1/customer-tagging/requests",
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function reviewCustomerTagChangeRequest(
  requestId: number,
  decisions: Array<{
    item_id: number;
    decision: "approved" | "need_supplement" | "rejected";
    comment?: string;
  }>,
  comment?: string,
) {
  return requestJson<CustomerTagChangeRequest>(
    `/api/v1/customer-tagging/requests/${requestId}/review`,
    {
      method: "POST",
      body: JSON.stringify({ decisions, comment }),
    },
  );
}

export function supplementCustomerTagChangeRequest(
  requestId: number,
  items: Array<{
    item_id: number;
    evidence: string;
    review_date?: string | null;
    owner_user_id?: number | null;
    details_json?: Record<string, unknown>;
  }>,
  comment?: string,
) {
  return requestJson<CustomerTagChangeRequest>(
    `/api/v1/customer-tagging/requests/${requestId}/supplement`,
    { method: "POST", body: JSON.stringify({ items, comment }) },
  );
}

export function customerTagLegacyMappings(
  options: { status?: string; customerCode?: string } = {},
) {
  const params = new URLSearchParams();
  if (options.status) params.set("status_value", options.status);
  if (options.customerCode) params.set("customer_code", options.customerCode);
  return requestJson<
    Array<{
      id: number;
      customer_code: string;
      legacy_tag_name: string;
      target_tag_id?: number | null;
      target_tag_name?: string | null;
      confidence?: number | null;
      rationale?: string | null;
      status: string;
    }>
  >(
    `/api/v1/customer-tagging/legacy-mappings${params.size ? `?${params}` : ""}`,
  );
}

export function reviewCustomerTagLegacyMapping(
  mappingId: number,
  payload: {
    target_tag_id?: number;
    decision: "submit" | "reject" | "unmatched";
    evidence: string;
    reviewer_user_id?: number;
    attribute_type?: "long_term" | "temporary";
    review_date?: string | null;
    owner_user_id?: number | null;
    is_primary?: boolean;
    details_json?: Record<string, unknown>;
  },
) {
  return requestJson<Record<string, unknown>>(
    `/api/v1/customer-tagging/legacy-mappings/${mappingId}/review`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function salesOrders(
  options: {
    q?: string;
    status?: string;
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.q) params.set("q", options.q);
  if (options.status) params.set("status_value", options.status);
  return requestJson<{
    items: SalesOrderRow[];
    total: number;
    limit: number;
    offset: number;
  }>(`/api/v1/fulfillment/orders?${params}`);
}

export function salesOrder(orderId: number, includeRequirementDiff = false) {
  return requestJson<SalesOrderRow>(
    `/api/v1/fulfillment/orders/${orderId}?include_requirement_diff=${includeRequirementDiff}`,
  );
}

export function createSalesOrder(payload: {
  external_order_no?: string;
  customer_code: string;
  planned_delivery_at?: string | null;
  delivery_address?: string | null;
  temporary_requirements?: Array<Record<string, unknown>>;
  lines: SalesOrderLinePayload[];
}) {
  return requestJson<SalesOrderRow>("/api/v1/fulfillment/orders", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function importSalesOrders(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<SalesOrderImportResult>(
    "/api/v1/fulfillment/orders/import",
    { method: "POST", body: formData },
  );
}

export function confirmSalesOrder(orderId: number) {
  return requestJson<SalesOrderRow>(
    `/api/v1/fulfillment/orders/${orderId}/confirm`,
    { method: "POST" },
  );
}

export function cancelSalesOrder(orderId: number, reason: string) {
  return requestJson<SalesOrderRow>(
    `/api/v1/fulfillment/orders/${orderId}/cancel`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
  );
}

export function refreshSalesOrderRequirements(orderId: number) {
  return requestJson<SalesOrderRow>(
    `/api/v1/fulfillment/orders/${orderId}/refresh-requirements`,
    { method: "POST" },
  );
}

export function deliveryTasks(
  options: { status?: string; limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.status) params.set("status_value", options.status);
  return requestJson<{
    items: DeliveryTaskRow[];
    total: number;
    limit: number;
    offset: number;
  }>(`/api/v1/fulfillment/deliveries?${params}`);
}

export function updateDeliveryTask(
  deliveryId: number,
  payload: {
    event_type: string;
    to_status: string;
    note?: string;
    assignee_user_id?: number;
    signed_by?: string;
    signed_at?: string;
  },
) {
  return requestJson<DeliveryTaskRow>(
    `/api/v1/fulfillment/deliveries/${deliveryId}/events`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function uploadDeliveryAttachment(deliveryId: number, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<DeliveryAttachmentRow>(
    `/api/v1/fulfillment/deliveries/${deliveryId}/attachments`,
    { method: "POST", body: formData },
  );
}

export async function downloadDeliveryAttachment(
  deliveryId: number,
  attachmentId: number,
) {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(
    `/api/v1/fulfillment/deliveries/${deliveryId}/attachments/${attachmentId}/download`,
    {
      headers,
      credentials: "include",
    },
  );
  if (!response.ok) {
    const raw = await response.text();
    throw new Error(apiErrorMessage(response.status, raw));
  }
  return response.blob();
}

export function updateAccountLedgerEntry(
  entryId: number,
  payload: Record<string, string | number | null>,
) {
  return requestJson<AccountLedgerRow>(
    `/api/v1/process-data/account-ledger/${entryId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function receivablesPage(
  options: {
    q?: string;
    dateFrom?: string;
    dateTo?: string;
    customerCode?: string;
    customerName?: string;
    salespersonName?: string;
    matchStatus?: string;
    riskType?: string;
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.q) params.set("q", options.q);
  if (options.dateFrom) params.set("date_from", options.dateFrom);
  if (options.dateTo) params.set("date_to", options.dateTo);
  if (options.customerCode) params.set("customer_code", options.customerCode);
  if (options.customerName) params.set("customer_name", options.customerName);
  if (options.salespersonName)
    params.set("salesperson_name", options.salespersonName);
  if (options.matchStatus) params.set("match_status", options.matchStatus);
  if (options.riskType) params.set("risk_type", options.riskType);
  return requestJson<ReceivablePage>(`/api/v1/receivables/page?${params}`);
}

export function receivableSummary() {
  return requestJson<ReceivableSummary>("/api/v1/receivables/summary");
}

export function receivableTimeline(options: {
  customerCode?: string;
  customerName?: string;
  limit?: number;
}) {
  const params = new URLSearchParams({ limit: String(options.limit ?? 30) });
  if (options.customerCode) params.set("customer_code", options.customerCode);
  if (options.customerName) params.set("customer_name", options.customerName);
  return requestJson<{ items: ReceivableRow[]; total: number; limit: number }>(
    `/api/v1/receivables/timeline?${params}`,
  );
}

export function receivableCheckResults(
  options: {
    resultType?: string;
    q?: string;
    dateFrom?: string;
    dateTo?: string;
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.resultType) params.set("result_type", options.resultType);
  if (options.q) params.set("q", options.q);
  if (options.dateFrom) params.set("date_from", options.dateFrom);
  if (options.dateTo) params.set("date_to", options.dateTo);
  return requestJson<ReceivableCheckResultPage>(
    `/api/v1/receivables/check-results?${params}`,
  );
}

export function rebuildReceivableCheck(batchId?: number) {
  const params = new URLSearchParams();
  if (batchId) params.set("batch_id", String(batchId));
  return requestJson<Record<string, number>>(
    `/api/v1/receivables/rebuild-check${params.toString() ? `?${params}` : ""}`,
    { method: "POST" },
  );
}

export function processDetailContext(
  payload: Record<string, string | number | null | undefined> & {
    kind: ProcessDetailContextKind;
    limit?: number;
  },
) {
  return requestJson<ProcessDetailContextResult>(
    "/api/v1/context/process-detail",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function updateEmployee(
  employeeCode: string,
  payload: EmployeeUpdatePayload,
) {
  return requestJson<MasterRow>(
    `/api/v1/employees/${encodeURIComponent(employeeCode)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function roles() {
  return requestJson<RoleRow[]>("/api/v1/admin/roles");
}

export function createRoleTemplate(payload: RoleCreatePayload) {
  return requestJson<RolePermissions>("/api/v1/admin/roles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function users(q = "", status = "") {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status) params.set("status_value", status);
  return requestJson<UserPublic[]>(
    `/api/v1/users${params.toString() ? `?${params}` : ""}`,
  );
}

export function createUser(payload: {
  username: string;
  password: string;
  real_name: string;
  employee_code?: string | null;
  role: string;
  status: string;
}) {
  return requestJson<UserPublic>("/api/v1/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateUser(
  userId: number,
  payload: { real_name?: string; employee_code?: string | null; role?: string },
) {
  return requestJson<UserPublic>(`/api/v1/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function uploadMyAvatar(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<UserPublic>("/api/v1/users/me/avatar", {
    method: "POST",
    body: formData,
  });
}

export function deleteMyAvatar() {
  return requestJson<UserPublic>("/api/v1/users/me/avatar", {
    method: "DELETE",
  });
}

export function uploadUserAvatar(userId: number, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<UserPublic>(`/api/v1/users/${userId}/avatar`, {
    method: "POST",
    body: formData,
  });
}

export function deleteUserAvatar(userId: number) {
  return requestJson<UserPublic>(`/api/v1/users/${userId}/avatar`, {
    method: "DELETE",
  });
}

export function resetUserPassword(userId: number, password: string) {
  return requestJson<UserPublic>(`/api/v1/users/${userId}/reset-password`, {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

export function disableUser(userId: number, reason = "") {
  return requestJson<UserPublic>(`/api/v1/users/${userId}/disable`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function restoreUser(userId: number, reason = "") {
  return requestJson<UserPublic>(`/api/v1/users/${userId}/restore`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function cancelUser(userId: number, reason = "") {
  return requestJson<UserPublic>(`/api/v1/users/${userId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function userStatusHistory(userId: number) {
  return requestJson<UserStatusHistory[]>(
    `/api/v1/users/${userId}/status-history`,
  );
}

export function userPermissions(userId: number) {
  return requestJson<UserPermissions>(`/api/v1/users/${userId}/permissions`);
}

export function updateUserPermissions(
  userId: number,
  overrides: UserPermissionOverride[],
) {
  return requestJson<UserPermissions>(`/api/v1/users/${userId}/permissions`, {
    method: "PUT",
    body: JSON.stringify({ overrides }),
  });
}

export function resetUserPermissionsToRole(userId: number) {
  return requestJson<UserPermissions>(
    `/api/v1/users/${userId}/permissions/reset-to-role`,
    { method: "POST" },
  );
}

export function permissions() {
  return requestJson<PermissionRow[]>("/api/v1/admin/permissions");
}

export function rolePermissions(roleCode: string) {
  return requestJson<RolePermissions>(
    `/api/v1/admin/roles/${roleCode}/permissions`,
  );
}

export function updateRolePermissions(
  roleCode: string,
  permissionCodes: string[],
) {
  return requestJson<RolePermissions>(
    `/api/v1/admin/roles/${roleCode}/permissions`,
    {
      method: "PUT",
      body: JSON.stringify({ permission_codes: permissionCodes }),
    },
  );
}

export function authorityRules() {
  return requestJson<AuthorityRule[]>("/api/v1/admin/authority-root-rules");
}

export function dataScopeRules(subjectType = "", subjectId = "") {
  const params = new URLSearchParams();
  if (subjectType) params.set("subject_type", subjectType);
  if (subjectId) params.set("subject_id", subjectId);
  return requestJson<DataScopeRule[]>(
    `/api/v1/admin/data-scope-rules${params.toString() ? `?${params}` : ""}`,
  );
}

export function fieldPermissionRules(subjectType = "", subjectId = "") {
  const params = new URLSearchParams();
  if (subjectType) params.set("subject_type", subjectType);
  if (subjectId) params.set("subject_id", subjectId);
  return requestJson<FieldPermissionRule[]>(
    `/api/v1/admin/field-permission-rules${params.toString() ? `?${params}` : ""}`,
  );
}

export function auditLogs(
  filters: {
    limit?: number;
    resource_id?: string;
    resource_type?: string;
    user_id?: number;
  } = {},
) {
  const params = new URLSearchParams({ limit: String(filters.limit ?? 30) });
  if (filters.resource_id) params.set("resource_id", filters.resource_id);
  if (filters.resource_type) params.set("resource_type", filters.resource_type);
  if (filters.user_id) params.set("user_id", String(filters.user_id));
  return requestJson<AuditLog[]>(`/api/v1/admin/audit-logs?${params}`);
}

export type CrmProjectRow = {
  id: number;
  project_code: string;
  project_name: string;
  project_type?: string | null;
  purpose?: string | null;
  customer_scope_note?: string | null;
  business_line?: string | null;
  applicant_user_id?: number | null;
  landing_approver_user_id?: number | null;
  owner_user_id?: number | null;
  project_manager_user_id?: number | null;
  participant_user_ids?: number[] | null;
  progress_cc_user_ids?: number[] | null;
  applicant_user_label?: string | null;
  landing_approver_user_label?: string | null;
  owner_user_label?: string | null;
  project_manager_user_label?: string | null;
  participant_user_labels?: string[];
  progress_cc_user_labels?: string[];
  assignment_mode?: string | null;
  allow_unassigned_tasks?: boolean | null;
  start_date?: string | null;
  due_date?: string | null;
  minimum_action?: string | null;
  closure_standard?: string | null;
  status: string;
  approval_status: string;
  current_approval_id?: number | null;
  approval_withdrawn_at?: string | null;
  approval_withdrawn_by_user_id?: number | null;
  approval_withdrawn_by_user_label?: string | null;
  approval_withdrawn_reason?: string | null;
  next_step_status?: string | null;
  next_step_action?: string | null;
  next_step_followup_at?: string | null;
  task_total?: number;
  task_closed?: number;
  task_open?: number;
  task_need_support?: number;
  task_blocked?: number;
  task_overdue?: number;
  followed_customer_count?: number;
  progress_percent?: number;
  support_item_open?: number;
  pending_approval_count?: number;
  latest_followup_at?: string | null;
  created_by_user_id?: number | null;
  updated_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type CrmLeadProductIntent = {
  id: number;
  lead_id: number;
  product_code?: string | null;
  product_name: string;
  quantity_note?: string | null;
  interest_level?: string | null;
  note?: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type CrmLeadFollowup = {
  id: number;
  lead_id: number;
  followup_no: string;
  content: string;
  method?: string | null;
  outcome?: string | null;
  next_action?: string | null;
  next_followup_at?: string | null;
  created_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type CrmLeadAssignmentEvent = {
  id: number;
  lead_id: number;
  from_assignee_user_id?: number | null;
  to_assignee_user_id?: number | null;
  assigned_by_user_id?: number | null;
  note?: string | null;
  created_at: string;
};

export type CrmLeadRow = {
  id: number;
  lead_no: string;
  lead_name: string;
  company_name?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  source?: string | null;
  campaign_id?: number | null;
  region?: string | null;
  address?: string | null;
  customer_group_name?: string | null;
  business_line?: string | null;
  intent_summary?: string | null;
  status: string;
  priority?: "low" | "normal" | "high" | "urgent" | string;
  pool_status?: "private" | "public" | string;
  qualification_note?: string | null;
  owner_user_id?: number | null;
  assigned_user_id?: number | null;
  assigned_at?: string | null;
  assignment_expires_at?: string | null;
  first_response_due_at?: string | null;
  first_responded_at?: string | null;
  last_activity_at?: string | null;
  last_followup_at?: string | null;
  next_followup_at?: string | null;
  recycled_at?: string | null;
  recycle_count?: number;
  current_approval_id?: number | null;
  converted_customer_code?: string | null;
  converted_at?: string | null;
  converted_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
  product_intents: CrmLeadProductIntent[];
  followups: CrmLeadFollowup[];
  assignments: CrmLeadAssignmentEvent[];
};

export type CrmLeadPage = {
  items: CrmLeadRow[];
  total: number;
  limit: number;
  offset: number;
  summary: {
    total: number;
    by_status: Record<string, number>;
  };
};

export type CrmLeadDuplicateCheck = {
  has_blocking_duplicates: boolean;
  requires_acknowledgement: boolean;
  has_hidden_duplicates: boolean;
  items: Array<{
    lead_id: number;
    lead_no: string;
    lead_name: string;
    contact_phone?: string | null;
    reasons: string[];
    blocking: boolean;
    similarity: number;
  }>;
};

export type CrmLeadAssigneeOption = {
  id: number;
  name: string;
  username: string;
  label: string;
};

export type CrmLeadAnalytics = {
  summary: {
    total: number;
    by_status: Record<string, number>;
    overdue_next_followup: number;
  };
  dimensions: {
    sources: Array<{ value?: string | null; count: number }>;
    regions: Array<{ value?: string | null; count: number }>;
    business_lines: Array<{ value?: string | null; count: number }>;
  };
  operations?: CrmLeadOperationsAnalytics;
};

export type CrmLeadOperationsAnalytics = {
  team_funnel: Array<{
    user_id?: number | null;
    user_label: string;
    total: number;
    by_status: Record<string, number>;
  }>;
  source_funnel: Array<{
    source: string;
    total: number;
    by_status: Record<string, number>;
  }>;
  campaign_funnel: Array<{
    campaign_id?: number | null;
    campaign_code?: string | null;
    campaign_name: string;
    total: number;
    by_status: Record<string, number>;
  }>;
  sla_exceptions: { overdue: number; due_soon: number; unassigned: number };
  assignment_load: Array<{
    user_id: number;
    user_label: string;
    assigned_total: number;
    open_total: number;
    overdue: number;
    due_soon: number;
  }>;
  recycle_metrics: {
    recycled_leads: number;
    recycle_total: number;
    recycle_events: number;
    claim_events: number;
  };
};

export type CrmLeadSlaSnapshot = {
  state: "overdue" | "due_soon" | "unassigned" | "normal" | string;
  phase: "first_response" | "next_followup" | "closed" | string;
  deadline?: string | null;
  remaining_seconds?: number | null;
};

export type CrmLeadPoolRow = {
  id: number;
  lead_no: string;
  lead_name: string;
  company_name?: string | null;
  source?: string | null;
  region?: string | null;
  business_line?: string | null;
  priority: "low" | "normal" | "high" | "urgent" | string;
  pool_status: "public" | string;
  status: string;
  first_response_due_at?: string | null;
  recycled_at?: string | null;
  recycle_count: number;
  created_at: string;
  sla: CrmLeadSlaSnapshot;
};

export type CrmLeadCampaignRow = {
  id: number;
  campaign_code: string;
  campaign_name: string;
  source?: string | null;
  channel?: string | null;
  description?: string | null;
  status: "draft" | "active" | "paused" | "closed" | string;
  start_date?: string | null;
  end_date?: string | null;
  owner_user_id?: number | null;
  created_by_user_id?: number | null;
  updated_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type CrmLeadCampaignPage = {
  items: CrmLeadCampaignRow[];
  total: number;
  limit: number;
  offset: number;
};

export type CrmLeadOperationPolicy = {
  id: number;
  policy_key: string;
  first_response_hours: number;
  next_followup_hours: number;
  assignment_hold_hours: number;
  due_soon_hours: number;
  daily_claim_limit: number;
  is_active: boolean;
  updated_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type CrmLeadSlaExceptionPage = {
  items: Array<{ lead: CrmLeadRow; sla: CrmLeadSlaSnapshot }>;
  total: number;
  limit: number;
  offset: number;
};

export type CrmLeadUpdatePayload = Partial<
  Pick<
    CrmLeadRow,
    | "lead_name"
    | "company_name"
    | "contact_name"
    | "contact_phone"
    | "source"
    | "campaign_id"
    | "region"
    | "address"
    | "customer_group_name"
    | "business_line"
    | "intent_summary"
    | "status"
    | "priority"
    | "qualification_note"
    | "owner_user_id"
    | "assigned_user_id"
    | "next_followup_at"
  >
> & {
  duplicate_acknowledged?: boolean;
  product_intents?: Array<{
    product_code?: string | null;
    product_name: string;
    quantity_note?: string | null;
    interest_level?: string | null;
    note?: string | null;
    sort_order?: number;
  }>;
};

export type CrmTaskRow = {
  id: number;
  project_id: number;
  task_code: string;
  customer_code: string;
  customer_name_snapshot: string;
  executor_user_id?: number | null;
  executor_employee_code?: string | null;
  executor_name_snapshot?: string | null;
  business_issue_point?: string | null;
  round_target?: string | null;
  feedback_due_at?: string | null;
  status: string;
  minimum_action_done: boolean;
  need_support: boolean;
  need_manager_support: boolean;
  need_boss_decision: boolean;
  is_blocked: boolean;
  is_closed: boolean;
  latest_followup_id?: number | null;
  latest_blocker_reason?: string | null;
  latest_blocker_note?: string | null;
  latest_owner_next_status?: string | null;
  latest_owner_next_action?: string | null;
  latest_owner_next_followup_at?: string | null;
  last_followup_at?: string | null;
  followup_submission_state?:
    | "unsubmitted"
    | "submitted"
    | "needs_action"
    | null;
  latest_followup_approval_status?: string | null;
  latest_followup_submitted_at?: string | null;
  project_purpose?: string | null;
  data_update_total?: number;
  data_update_pending?: number;
  latest_data_update_at?: string | null;
  customer_profile_approval_id?: number | null;
  customer_profile_approval_status?: string | null;
  business_profile_approval_id?: number | null;
  business_profile_approval_status?: string | null;
  created_at: string;
  updated_at: string;
};

export type CrmFollowupRow = {
  id: number;
  followup_no: string;
  project_id: number;
  task_id: number;
  customer_code: string;
  customer_name?: string | null;
  project_name?: string | null;
  executor_user_id?: number | null;
  executor_name_snapshot?: string | null;
  followup_date?: string | null;
  method?: string | null;
  frontline_action?: string | null;
  customer_feedback?: string | null;
  current_need?: string | null;
  need_type?: string | null;
  blocker_reason?: string | null;
  blocker_note?: string | null;
  next_action_type?: string | null;
  next_action?: string | null;
  next_followup_at?: string | null;
  minimum_action_done: boolean;
  business_profile_updated: boolean;
  business_profile_approval_id?: number | null;
  customer_profile_updated: boolean;
  customer_profile_approval_id?: number | null;
  need_support: boolean;
  need_manager_support: boolean;
  need_boss_decision: boolean;
  is_closed: boolean;
  valid_feedback: boolean;
  review_status: string;
  review_result?: string | null;
  review_note?: string | null;
  owner_next_status?: string | null;
  owner_next_action?: string | null;
  owner_next_followup_at?: string | null;
  reviewed_by_user_id?: number | null;
  reviewed_at?: string | null;
  approval_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type CrmProjectReviewRow = {
  id: number;
  review_no: string;
  project_id: number;
  review_date?: string | null;
  status: string;
  customer_total: number;
  feedback_customer_count: number;
  valid_feedback_customer_count: number;
  no_feedback_customer_count: number;
  support_item_count: number;
  closed_customer_count: number;
  unclosed_customer_count: number;
  data_summary?: string | null;
  business_judgement?: string | null;
  main_problem?: string | null;
  next_suggestion?: string | null;
  conclusion?: string | null;
  decision_maker_user_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type WorkItemRow = {
  id: number;
  item_no: string;
  source_type: string;
  source_id: string;
  resource_type?: string | null;
  resource_id?: string | null;
  project_id?: number | null;
  customer_code?: string | null;
  item_type: string;
  title: string;
  detail?: string | null;
  priority: string;
  status: string;
  assignee_user_id?: number | null;
  due_at?: string | null;
  resolved_by_user_id?: number | null;
  resolved_at?: string | null;
  resolution_note?: string | null;
  created_at: string;
  updated_at: string;
  customer_name?: string | null;
  project_name?: string | null;
  project_approval_frozen?: boolean;
  project_approval_withdrawn_reason?: string | null;
  project_approval_withdrawn_at?: string | null;
  task_no?: string | null;
  task_title?: string | null;
  assignee_name?: string | null;
  resolved_by_name?: string | null;
  support_type?: string | null;
  support_detail?: string | null;
  source_followup_summary?: string | null;
  needs_next_action?: boolean;
};

export type WorkItemPage = {
  items: WorkItemRow[];
  total: number;
  limit: number;
  offset: number;
};

export type WorkItemUpdatePayload = {
  title?: string | null;
  detail?: string | null;
  priority?: string | null;
  status?: string | null;
  assignee_user_id?: number | null;
  due_at?: string | null;
};

export type WorkItemActionPayload = {
  resolution_note?: string | null;
};

export type CrmSummary = {
  active_projects: number;
  pending_project_approvals: number;
  task_total: number;
  due_today_tasks: number;
  overdue_no_feedback_tasks: number;
  open_work_items: number;
  closed_tasks: number;
  valid_feedback_tasks: number;
  valid_feedback_rate: number;
  latest_followup_at?: string | null;
  generated_at: string;
};

export type CrmDailySummaryTask = {
  id: number;
  project_id: number;
  task_code: string;
  customer_code: string;
  customer_name_snapshot: string;
  executor_user_id?: number | null;
  executor_employee_code?: string | null;
  executor_name_snapshot?: string | null;
  feedback_due_at?: string | null;
  status: string;
  is_closed: boolean;
  last_followup_at?: string | null;
  latest_followup_id?: number | null;
  has_valid_followup: boolean;
  overdue: boolean;
};

export type CrmDailySummary = {
  date: string;
  due_tasks: CrmDailySummaryTask[];
  overdue_tasks: CrmDailySummaryTask[];
  task_total: number;
  due_count: number;
  overdue_count: number;
  responsible_user_ids: number[];
  missing_responsible_user_ids: number[];
  generated_at: string;
};

export type CrmReportNotification = {
  notification_id: string;
  notification_type: "today" | "overdue" | "supplement" | "support" | string;
  title: string;
  detail?: string | null;
  status: "pending" | "processed" | string;
  priority: "low" | "normal" | "high" | "urgent" | string;
  source_type: string;
  source_id: string;
  project_id?: number | null;
  task_id?: number | null;
  customer_code?: string | null;
  action_path?: string | null;
  created_at?: string | null;
  due_at?: string | null;
  is_mine: boolean;
};

export type CrmReportNotificationSummary = {
  total: number;
  pending: number;
  processed: number;
  today: number;
  overdue: number;
  supplement: number;
  support: number;
};

export type CrmReportNotificationCenter = {
  summary: CrmReportNotificationSummary;
  items: CrmReportNotification[];
  generated_at: string;
};

export type CrmReportNotificationProcessPayload = {
  action?: string;
  note?: string | null;
};

export type CrmReportNotificationProcessResult = {
  status: string;
  notification_id: string;
  action: string;
  audit_logged: boolean;
};

export type CrmReportKind =
  | "project-progress"
  | "weekly"
  | "monthly"
  | "support-items"
  | "followups";

export type CrmAssistantSkill = {
  operation: string;
  label: string;
  description: string;
  write_effect: string;
};

export type CrmAssistantRuntime = {
  configured: boolean;
  model?: string | null;
  provider_host?: string | null;
  source: string;
  direct_db_enabled: boolean;
  skills: CrmAssistantSkill[];
};

export type CrmAssistantConversation = {
  id: number;
  conversation_no: string;
  user_id?: number | null;
  username_snapshot?: string | null;
  channel: string;
  session_id?: string | null;
  context_type?: string | null;
  context_id?: string | null;
  operation?: string | null;
  user_message: string;
  assistant_message: string;
  source: string;
  model_name?: string | null;
  status: string;
  payload_json?: Record<string, unknown> | unknown[] | null;
  created_at: string;
};

export type CrmAssistantMessagePayload = {
  message: string;
  operation?: string | null;
  channel?: string;
  session_id?: string | null;
  context_type?: string | null;
  context_id?: string | null;
};

export type CrmProjectInsightRow = {
  id: number;
  insight_no: string;
  project_id?: number | null;
  task_id?: number | null;
  customer_code?: string | null;
  insight_type: string;
  summary: string;
  suggested_action?: string | null;
  risk_level: string;
  opportunity_level?: string | null;
  confidence_score: number;
  status: string;
  evidence_json?: Record<string, unknown> | unknown[] | null;
  source: string;
  generated_by_user_id?: number | null;
  reviewed_by_user_id?: number | null;
  reviewed_at?: string | null;
  review_note?: string | null;
  payload_json?: Record<string, unknown> | unknown[] | null;
  created_at: string;
  updated_at: string;
};

export type CrmProjectInsightPage = {
  items: CrmProjectInsightRow[];
  total: number;
  limit: number;
  offset: number;
};

export type CrmAssistantMessageResponse = {
  message: CrmAssistantConversation;
  runtime: CrmAssistantRuntime;
  insights_created: number;
};

export type CrmAssistantProjectDraftRequest = {
  project_name?: string | null;
  customer_name?: string | null;
  project_type?: string | null;
  business_line?: string | null;
  purpose?: string | null;
  customer_scope_note?: string | null;
  target?: string | null;
  risk_note?: string | null;
  due_days?: number;
  channel?: string;
};

export type CrmAssistantProjectDraft = {
  project: Partial<CrmProjectRow> & { project_name: string };
  tasks: Array<Partial<CrmTaskRow> & { customer_code?: string }>;
  suggestions: {
    target?: string | null;
    risk_note?: string | null;
    recommended_priority?: string | null;
    recommended_due_days?: number | null;
    manual_checks?: string[];
  };
};

export type CrmAssistantProjectDraftResponse = {
  draft: CrmAssistantProjectDraft;
  message: CrmAssistantConversation;
  runtime: CrmAssistantRuntime;
};

export type CrmAssistantAgentStatus = {
  runtime: CrmAssistantRuntime;
  status_counts: Record<string, number>;
  source_counts: Record<string, number>;
  operation_counts: Record<string, number>;
  pending_actions: number;
  recent_calls: CrmAssistantConversation[];
  last_call_at?: string | null;
  migration_status?: Record<string, unknown>;
};

export type CrmAssistantJudgementResult = {
  created: number;
  skipped: number;
  insights: CrmProjectInsightRow[];
};

export type CrmProjectPage = {
  items: CrmProjectRow[];
  total: number;
  limit: number;
  offset: number;
};

export type CrmTestProjectCounts = {
  task_total: number;
  followup_total: number;
  review_total: number;
  approval_total: number;
  work_item_total: number;
  open_work_item_total: number;
  pending_approval_total: number;
  latest_activity_at?: string | null;
};

export type CrmTestProjectCandidate = {
  project: CrmProjectRow;
  test_reasons: string[];
  counts: CrmTestProjectCounts;
  can_void: boolean;
};

export type CrmTestProjectPage = {
  items: CrmTestProjectCandidate[];
  total: number;
  limit: number;
  offset: number;
  marker?: string | null;
};

export type CrmVoidTestProjectPayload = {
  reason: string;
  confirmation: string;
};

export type CrmVoidTestProjectResult = {
  project: CrmProjectRow;
  test_reasons: string[];
  counts: CrmTestProjectCounts;
  message: string;
};

export type CrmTaskPage = {
  items: CrmTaskRow[];
  total: number;
  limit: number;
  offset: number;
  submission_summary: {
    total: number;
    submitted: number;
    unsubmitted: number;
    needs_action: number;
  };
};

export type CrmProjectCustomerDetailSummary = {
  total: number;
  open: number;
  closed: number;
  overdue: number;
  need_support: number;
  need_manager_support: number;
  need_boss_decision: number;
  blocked: number;
  customer_groups: string[];
  salespersons: string[];
  regions: string[];
  customer_types: string[];
  customer_statuses: string[];
  task_statuses: string[];
  blocker_reasons: string[];
};

export type CrmProjectCustomerDetailRow = CrmTaskRow & {
  customer_name?: string | null;
  customer_short_name?: string | null;
  customer_type?: string | null;
  customer_status?: string | null;
  customer_group_name?: string | null;
  region?: string | null;
  salesperson_name?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  task_status: string;
  overdue: boolean;
};

export type CrmProjectCustomerDetailPage = {
  items: CrmProjectCustomerDetailRow[];
  total: number;
  limit: number;
  offset: number;
  summary: CrmProjectCustomerDetailSummary;
};

export type CrmLinkedCustomerSummary = {
  total_customers: number;
  project_total: number;
  task_total: number;
  task_open: number;
  task_closed: number;
  task_overdue: number;
  task_need_support: number;
  task_blocked: number;
  task_status_counts?: Record<string, number>;
  followup_total: number;
  work_item_open: number;
  profile_incomplete: number;
  pending_action_customers: number;
  risk_customers: number;
  generated_at?: string | null;
};

export type CrmLinkedCustomerRow = {
  customer_code: string;
  customer_name: string;
  customer_name_snapshot?: string | null;
  customer_short_name?: string | null;
  customer_type?: string | null;
  customer_status?: string | null;
  region?: string | null;
  salesperson_employee_code?: string | null;
  salesperson_name?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  contact_channel?: string | null;
  customer_group_name?: string | null;
  customer_tags?: string[];
  address?: string | null;
  base_info_completeness?: string | null;
  profile_updated_at?: string | null;
  customer_updated_at?: string | null;
  base_remark?: string | null;
  project_total: number;
  latest_project_id?: number | null;
  latest_project_name?: string | null;
  latest_project_status?: string | null;
  task_total: number;
  task_open: number;
  task_closed: number;
  task_overdue: number;
  task_need_support: number;
  task_blocked: number;
  task_status_counts?: Record<string, number>;
  followup_total: number;
  latest_followup_at?: string | null;
  work_item_open: number;
  executor_names: string[];
  latest_task_id?: number | null;
  latest_task_code?: string | null;
  latest_task_status?: string | null;
  latest_owner_next_status?: string | null;
  latest_owner_next_action?: string | null;
  latest_owner_next_followup_at?: string | null;
  latest_blocker_reason?: string | null;
  current_flow_node?: string | null;
  current_handler_label?: string | null;
  blocked_reason_summary?: string | null;
  flow_status?: string | null;
  last_activity_at?: string | null;
  risk_level: string;
};

export type CrmLinkedCustomerPage = {
  items: CrmLinkedCustomerRow[];
  total: number;
  limit: number;
  offset: number;
  summary: CrmLinkedCustomerSummary;
};

export type CrmDataCenterBucket = {
  value: string;
  label: string;
  count: number;
  risk_count: number;
  meta?: Record<string, unknown> | unknown[] | null;
};

export type CrmDataCenterSummary = {
  project_total: number;
  task_total: number;
  open_tasks: number;
  closed_tasks: number;
  overdue_tasks: number;
  need_support_tasks: number;
  blocked_tasks: number;
  no_followup_tasks: number;
  valid_feedback_tasks: number;
  open_work_items: number;
  pending_approvals: number;
  generated_at?: string | null;
};

export type CrmDataCenterDimensions = {
  projects: CrmDataCenterBucket[];
  owners: CrmDataCenterBucket[];
  regions: CrmDataCenterBucket[];
  customer_types: CrmDataCenterBucket[];
  blocker_reasons: CrmDataCenterBucket[];
  followup_statuses: CrmDataCenterBucket[];
};

export type CrmDataCenterTaskRow = CrmProjectCustomerDetailRow & {
  project_name?: string | null;
  project_code?: string | null;
  project_status?: string | null;
  project_owner_user_id?: number | null;
  project_manager_user_id?: number | null;
  followup_status: string;
  risk_level: string;
};

export type CrmDataCenterPage = {
  items: CrmDataCenterTaskRow[];
  total: number;
  limit: number;
  offset: number;
  scope?: string | null;
  summary: CrmDataCenterSummary;
  dimensions: CrmDataCenterDimensions;
};

export type CrmTaskDetail = {
  task: CrmTaskRow;
  project: CrmProjectRow;
  followups: CrmFollowupRow[];
  approvals: ApprovalRow[];
  work_items: WorkItemRow[];
};

export type CrmFollowupPage = {
  items: CrmFollowupRow[];
  total: number;
  limit: number;
  offset: number;
};

export type CrmProjectClosureSummary = {
  task_total: number;
  task_closed: number;
  task_open: number;
  task_need_support: number;
  task_blocked: number;
  task_overdue: number;
  feedback_task_count: number;
  valid_feedback_task_count: number;
  no_feedback_task_count: number;
  support_open_count: number;
  support_closed_count: number;
  pending_approval_count: number;
  review_total: number;
  review_confirmed: number;
  latest_review_status?: string | null;
  latest_review_conclusion?: string | null;
  closure_ready: boolean;
  closure_state: string;
};

export type CrmProjectDetail = {
  project: CrmProjectRow;
  task_summary: Record<string, number>;
  latest_followup?: CrmFollowupRow | null;
  support_item_count: number;
  approval_summary: Record<string, number>;
  review_summary: Record<string, number>;
  closure_summary: CrmProjectClosureSummary;
};

export type CrmProjectContext = {
  project_detail: CrmProjectDetail;
  tasks: CrmTaskRow[];
  followups: CrmFollowupRow[];
  approvals: ApprovalRow[];
  work_items: WorkItemRow[];
  reviews: CrmProjectReviewRow[];
};

export type CustomerCrmContext = {
  available: boolean;
  projects: CrmProjectRow[];
  tasks: CrmTaskRow[];
  followups: CrmFollowupRow[];
  approvals: ApprovalRow[];
  work_items: WorkItemRow[];
  flow_nodes?: CrmCustomerFlowNode[];
  stats: {
    project_total: number;
    task_total: number;
    task_open: number;
    task_closed: number;
    task_need_support: number;
    task_blocked: number;
    followup_total: number;
    work_item_open: number;
    approval_pending: number;
  };
};

export type CrmCustomerFlowNode = {
  key: string;
  label: string;
  status: string;
  handler_label?: string | null;
  at?: string | null;
  waiting_for_current_user?: boolean;
  approval_id?: number | null;
  count?: number;
};

export type CustomerContextResult = {
  customer: MasterRow;
  business_profile?: {
    profile?: CustomerBusinessProfile | null;
    products?: CustomerBusinessProduct[];
  } | null;
  portrait?: Record<string, unknown> | null;
  crm: CustomerCrmContext;
  audit: AuditLog[];
};

export type ApprovalRow = {
  id: number;
  approval_no: string;
  approval_type: string;
  resource_type: string;
  resource_id: string;
  title: string;
  description?: string | null;
  applicant_user_id?: number | null;
  applicant_user_label?: string | null;
  current_handler_user_id?: number | null;
  current_handler_user_label?: string | null;
  status: string;
  priority: string;
  payload_json?: Record<string, unknown> | unknown[] | null;
  result_json?: Record<string, unknown> | unknown[] | null;
  business_summary?: Record<string, unknown> | null;
  latest_return_feedback?: {
    event_type: "supplement_request" | "reject";
    comment?: string | null;
    operator_user_id?: number | null;
    operator_user_label?: string | null;
    created_at: string;
  } | null;
  submitted_at?: string | null;
  reviewed_at?: string | null;
  closed_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type ApprovalEventRow = {
  id: number;
  approval_id: number;
  event_type: string;
  operator_user_id?: number | null;
  operator_user_label?: string | null;
  from_status?: string | null;
  to_status?: string | null;
  comment?: string | null;
  snapshot_json?: Record<string, unknown> | unknown[] | null;
  created_at: string;
};

export type ApprovalAttachmentRow = {
  id: number;
  approval_id: number;
  file_name: string;
  content_type?: string | null;
  size_bytes?: number | null;
  storage_path: string;
  file_digest?: string | null;
  created_by_user_id?: number | null;
  created_by_user_label?: string | null;
  created_at: string;
};

export type ApprovalPage = {
  items: ApprovalRow[];
  total: number;
  limit: number;
  offset: number;
};

export type ApprovalDetail = {
  approval: ApprovalRow;
  events: ApprovalEventRow[];
  attachments: ApprovalAttachmentRow[];
};

export type ApprovalWithdrawalPreview = {
  approval_id: number;
  project_id?: number | null;
  state: "available" | "unavailable" | "withdrawn" | string;
  can_withdraw: boolean;
  deadline?: string | null;
  is_override: boolean;
  blockers: string[];
  impact_counts: Record<string, number>;
  project_status?: string | null;
};

export type ApprovalActionPayload = {
  comment?: string | null;
  payload_json?: Record<string, unknown> | unknown[] | null;
  result_json?: Record<string, unknown> | null;
};

export type ApprovalDraftUpdatePayload = {
  title?: string | null;
  description?: string | null;
  current_handler_user_id?: number | null;
  priority?: string | null;
  payload_json?: Record<string, unknown> | unknown[] | null;
  comment?: string | null;
};

export type CrmProjectApprovalDraftPayload = {
  title?: string | null;
  description?: string | null;
  current_handler_user_id?: number | null;
  priority?: string;
  submit?: boolean;
  project: Partial<CrmProjectRow> & { project_name: string };
  tasks?: Array<Partial<CrmTaskRow> & { customer_code: string }>;
};

export type CrmFollowupApprovalDraftPayload = {
  title?: string | null;
  description?: string | null;
  current_handler_user_id?: number | null;
  priority?: string;
  submit?: boolean;
  followup: Partial<CrmFollowupRow> & { project_id: number; task_id: number };
};

export type CrmCustomerProfileApprovalDraftPayload = {
  title?: string | null;
  description?: string | null;
  priority?: string;
  submit?: boolean;
  profile: CustomerUpdatePayload;
};

export type CrmCustomerProfileUpdateResult = {
  customer: MasterRow;
  changed_fields: string[];
  audit_log_id?: number | null;
  task_id: number;
  project_id?: number | null;
  synced_to_master: boolean;
  change_items?: Array<Record<string, unknown>>;
};

export type CrmBusinessProfileUpdateResult = CustomerBusinessProfileResponse & {
  recommended_products?: CustomerRecommendedProductPayload[];
  changed_fields: string[];
  task_id: number;
  project_id?: number | null;
  synced_to_master: boolean;
};

type CrmQueryValue =
  | string
  | number
  | boolean
  | string[]
  | number[]
  | null
  | undefined;

function crmQuery(params: Record<string, CrmQueryValue>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") return;
    search.set(
      key,
      Array.isArray(value) ? JSON.stringify(value) : String(value),
    );
  });
  return search.toString() ? `?${search}` : "";
}

export function crmProjectsPage(filters: Record<string, CrmQueryValue> = {}) {
  return requestJson<CrmProjectPage>(
    `/api/v1/crm/projects/page${crmQuery(filters)}`,
  );
}

export function crmLeadsPage(
  filters: Record<string, CrmQueryValue> = {},
  options: RequestInit = {},
) {
  return requestJson<CrmLeadPage>(
    `/api/v1/crm/leads${crmQuery(filters)}`,
    options,
  );
}

export function crmLeadDetail(leadId: number, options: RequestInit = {}) {
  return requestJson<CrmLeadRow>(`/api/v1/crm/leads/${leadId}`, options);
}

export function crmLeadAssigneeOptions() {
  return requestJson<CrmLeadAssigneeOption[]>(
    "/api/v1/crm/leads/assignee-options",
  );
}

export function createCrmLead(payload: {
  lead_name: string;
  company_name?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  source?: string | null;
  region?: string | null;
  address?: string | null;
  customer_group_name?: string | null;
  business_line?: string | null;
  intent_summary?: string | null;
  owner_user_id?: number | null;
  assigned_user_id?: number | null;
  duplicate_acknowledged?: boolean;
  product_intents?: Array<{
    product_name: string;
    quantity_note?: string | null;
    interest_level?: string | null;
  }>;
}) {
  return requestJson<CrmLeadRow>("/api/v1/crm/leads", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function crmLeadAnalytics() {
  return requestJson<CrmLeadAnalytics>("/api/v1/crm/leads/analytics");
}

export function crmLeadPublicPoolPage(
  filters: Record<string, CrmQueryValue> = {},
  options: RequestInit = {},
) {
  return requestJson<{
    items: CrmLeadPoolRow[];
    total: number;
    limit: number;
    offset: number;
  }>(`/api/v1/crm/leads/public-pool${crmQuery(filters)}`, options);
}

export function crmLeadSlaExceptions(
  filters: Record<string, CrmQueryValue> = {},
  options: RequestInit = {},
) {
  return requestJson<CrmLeadSlaExceptionPage>(
    `/api/v1/crm/leads/sla-exceptions${crmQuery(filters)}`,
    options,
  );
}

export function claimCrmLead(leadId: number) {
  return requestJson<CrmLeadRow>(`/api/v1/crm/leads/${leadId}/claim`, {
    method: "POST",
  });
}

export function recycleCrmLead(
  leadId: number,
  payload: { note?: string | null },
) {
  return requestJson<CrmLeadRow>(`/api/v1/crm/leads/${leadId}/recycle`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function crmLeadCampaignsPage(
  filters: Record<string, CrmQueryValue> = {},
) {
  return requestJson<CrmLeadCampaignPage>(
    `/api/v1/crm/lead-campaigns${crmQuery(filters)}`,
  );
}

export function createCrmLeadCampaign(
  payload: Omit<
    CrmLeadCampaignRow,
    | "id"
    | "created_at"
    | "updated_at"
    | "created_by_user_id"
    | "updated_by_user_id"
  >,
) {
  return requestJson<CrmLeadCampaignRow>("/api/v1/crm/lead-campaigns", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateCrmLeadCampaign(
  campaignId: number,
  payload: Partial<
    Omit<
      CrmLeadCampaignRow,
      | "id"
      | "created_at"
      | "updated_at"
      | "created_by_user_id"
      | "updated_by_user_id"
    >
  >,
) {
  return requestJson<CrmLeadCampaignRow>(
    `/api/v1/crm/lead-campaigns/${campaignId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export function crmLeadOperationPolicy() {
  return requestJson<CrmLeadOperationPolicy>(
    "/api/v1/crm/lead-operation-policy",
  );
}

export function updateCrmLeadOperationPolicy(
  payload: Partial<
    Pick<
      CrmLeadOperationPolicy,
      | "first_response_hours"
      | "next_followup_hours"
      | "assignment_hold_hours"
      | "due_soon_hours"
      | "daily_claim_limit"
    >
  >,
) {
  return requestJson<CrmLeadOperationPolicy>(
    "/api/v1/crm/lead-operation-policy",
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export function crmLeadDuplicateCheck(
  filters: {
    lead_name?: string;
    contact_phone?: string;
    exclude_lead_id?: number;
  } = {},
) {
  return requestJson<CrmLeadDuplicateCheck>(
    `/api/v1/crm/leads/duplicate-check${crmQuery(filters)}`,
  );
}

export function updateCrmLead(leadId: number, payload: CrmLeadUpdatePayload) {
  return requestJson<CrmLeadRow>(`/api/v1/crm/leads/${leadId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function assignCrmLead(
  leadId: number,
  payload: { assigned_user_id?: number | null; note?: string | null },
) {
  return requestJson<CrmLeadRow>(`/api/v1/crm/leads/${leadId}/assign`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createCrmLeadFollowup(
  leadId: number,
  payload: {
    content: string;
    method?: string | null;
    outcome?: string | null;
    next_action?: string | null;
    next_followup_at?: string | null;
  },
) {
  return requestJson<CrmLeadFollowup>(`/api/v1/crm/leads/${leadId}/followups`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createCrmLeadConversionApprovalDraft(
  leadId: number,
  payload: { submit: boolean; priority?: string; note?: string | null },
) {
  return requestJson<ApprovalRow>(
    `/api/v1/crm/leads/${leadId}/conversion-approval-draft`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function crmTestProjectsPage(
  filters: Record<string, CrmQueryValue> = {},
) {
  return requestJson<CrmTestProjectPage>(
    `/api/v1/crm/governance/test-projects${crmQuery(filters)}`,
  );
}

export function voidCrmTestProject(
  projectId: number,
  payload: CrmVoidTestProjectPayload,
) {
  return requestJson<CrmVoidTestProjectResult>(
    `/api/v1/crm/governance/test-projects/${projectId}/void`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function crmSummary() {
  return requestJson<CrmSummary>("/api/v1/crm/summary");
}

export function crmDataCenter(filters: Record<string, CrmQueryValue> = {}) {
  return requestJson<CrmDataCenterPage>(
    `/api/v1/crm/data-center${crmQuery(filters)}`,
  );
}

export function crmLinkedCustomersPage(
  filters: Record<string, CrmQueryValue> = {},
) {
  return requestJson<CrmLinkedCustomerPage>(
    `/api/v1/crm/linked-customers/page${crmQuery(filters)}`,
  );
}

export function crmLinkedCustomerContext(customerCode: string) {
  return requestJson<CustomerContextResult>(
    `/api/v1/crm/linked-customers/${encodeURIComponent(customerCode)}/context`,
  );
}

export function updateCrmLinkedCustomerBusinessProfile(
  customerCode: string,
  payload: CustomerBusinessProfilePayload,
) {
  return requestJson<CrmBusinessProfileUpdateResult>(
    `/api/v1/crm/linked-customers/${encodeURIComponent(customerCode)}/business-profile/update`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function createCrmCustomerProfileApprovalDraft(
  customerCode: string,
  payload: CrmCustomerProfileApprovalDraftPayload,
) {
  return requestJson<ApprovalRow>(
    `/api/v1/crm/linked-customers/${encodeURIComponent(customerCode)}/profile/approval-draft`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function updateCrmLinkedCustomerProfile(
  customerCode: string,
  payload: CustomerUpdatePayload,
) {
  return requestJson<CrmCustomerProfileUpdateResult>(
    `/api/v1/crm/linked-customers/${encodeURIComponent(customerCode)}/profile/update`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function crmDailySummary(filters: Record<string, CrmQueryValue> = {}) {
  return requestJson<CrmDailySummary>(
    `/api/v1/crm/daily-summary${crmQuery(filters)}`,
  );
}

export function crmReportNotifications() {
  return requestJson<CrmReportNotificationCenter>(
    "/api/v1/crm/reports/notifications",
  );
}

export function processCrmReportNotification(
  notificationId: string,
  payload: CrmReportNotificationProcessPayload = {},
) {
  return requestJson<CrmReportNotificationProcessResult>(
    `/api/v1/crm/reports/notifications/${encodeURIComponent(notificationId)}/process`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function downloadCrmReport(
  kind: CrmReportKind,
  filters: Record<string, CrmQueryValue> = {},
) {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(
    `/api/v1/crm/reports/${kind}.csv${crmQuery(filters)}`,
    {
      headers,
      credentials: "include",
    },
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(apiErrorMessage(response.status, text));
  }
  return response.blob();
}

export function crmAssistantRuntime() {
  return requestJson<CrmAssistantRuntime>("/api/v1/crm/assistant/runtime");
}

export function crmAssistantAgentStatus(signal?: AbortSignal) {
  return requestJson<CrmAssistantAgentStatus>("/api/v1/crm/assistant/agents", { signal });
}

export function crmAssistantMessages(
  filters: Record<string, CrmQueryValue> = {},
) {
  return requestJson<CrmAssistantConversation[]>(
    `/api/v1/crm/assistant/messages${crmQuery(filters)}`,
  );
}

export function clearCrmAssistantMessages(channel = "web") {
  return requestJson<{ deleted: number }>(
    `/api/v1/crm/assistant/messages${crmQuery({ channel })}`,
    { method: "DELETE" },
  );
}

export function sendCrmAssistantMessage(payload: CrmAssistantMessagePayload) {
  return requestJson<CrmAssistantMessageResponse>(
    "/api/v1/crm/assistant/messages",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function cancelCrmAssistantMessage(
  messageId: number,
  reason?: string | null,
) {
  return requestJson<CrmAssistantConversation>(
    `/api/v1/crm/assistant/messages/${messageId}/cancel`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
  );
}

export function generateCrmAssistantProjectDraft(
  payload: CrmAssistantProjectDraftRequest,
) {
  return requestJson<CrmAssistantProjectDraftResponse>(
    "/api/v1/crm/assistant/project-draft",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function generateCrmAssistantJudgements() {
  return requestJson<CrmAssistantJudgementResult>(
    "/api/v1/crm/assistant/daily-judgements",
    { method: "POST" },
  );
}

export function crmAssistantActionsPage(
  filters: Record<string, CrmQueryValue> = {},
) {
  return requestJson<CrmProjectInsightPage>(
    `/api/v1/crm/assistant/actions/page${crmQuery(filters)}`,
  );
}

export function crmAssistantInsightsPage(
  filters: Record<string, CrmQueryValue> = {},
) {
  return requestJson<CrmProjectInsightPage>(
    `/api/v1/crm/assistant/insights/page${crmQuery(filters)}`,
  );
}

export function reviewCrmAssistantInsight(
  insightId: number,
  action: "accept" | "reject" | "task",
  note?: string,
) {
  return requestJson<CrmProjectInsightRow>(
    `/api/v1/crm/assistant/insights/${insightId}/review`,
    {
      method: "POST",
      body: JSON.stringify({ action, note }),
    },
  );
}

export function crmProject(projectId: number) {
  return requestJson<CrmProjectDetail>(`/api/v1/crm/projects/${projectId}`);
}

export function crmProjectContext(projectId: number) {
  return requestJson<CrmProjectContext>(
    `/api/v1/crm/projects/${projectId}/context`,
  );
}

export function customerContext(customerCode: string) {
  return requestJson<CustomerContextResult>(
    `/api/v1/context/customers/${encodeURIComponent(customerCode)}`,
  );
}

export function workItemsPage(filters: Record<string, CrmQueryValue> = {}) {
  return requestJson<WorkItemPage>(
    `/api/v1/work-items/page${crmQuery(filters)}`,
  );
}

export function workItem(itemId: number) {
  return requestJson<WorkItemRow>(`/api/v1/work-items/${itemId}`);
}

export function updateWorkItem(itemId: number, payload: WorkItemUpdatePayload) {
  return requestJson<WorkItemRow>(`/api/v1/work-items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function resolveWorkItem(
  itemId: number,
  payload: WorkItemActionPayload = {},
) {
  return requestJson<WorkItemRow>(`/api/v1/work-items/${itemId}/resolve`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function closeWorkItem(
  itemId: number,
  payload: WorkItemActionPayload = {},
) {
  return requestJson<WorkItemRow>(`/api/v1/work-items/${itemId}/close`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createCrmProject(
  payload: Partial<CrmProjectRow> & { project_name: string },
) {
  return requestJson<CrmProjectRow>("/api/v1/crm/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateCrmProject(
  projectId: number,
  payload: Partial<CrmProjectRow>,
) {
  return requestJson<CrmProjectRow>(`/api/v1/crm/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function createCrmProjectApprovalDraft(
  payload: CrmProjectApprovalDraftPayload,
) {
  return requestJson<ApprovalRow>("/api/v1/crm/projects/approval-draft", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function crmProjectTasksPage(
  projectId: number,
  filters: Record<string, CrmQueryValue> = {},
) {
  return requestJson<CrmTaskPage>(
    `/api/v1/crm/projects/${projectId}/tasks/page${crmQuery(filters)}`,
  );
}

export function crmProjectCustomerDetailsPage(
  projectId: number,
  filters: Record<string, CrmQueryValue> = {},
) {
  return requestJson<CrmProjectCustomerDetailPage>(
    `/api/v1/crm/projects/${projectId}/customer-details/page${crmQuery(filters)}`,
  );
}

export function crmTasksPage(filters: Record<string, CrmQueryValue> = {}) {
  return requestJson<CrmTaskPage>(`/api/v1/crm/tasks/page${crmQuery(filters)}`);
}

const inFlightCrmTaskDetails = new Map<number, Promise<CrmTaskDetail>>();

export function crmTaskDetail(taskId: number) {
  const existing = inFlightCrmTaskDetails.get(taskId);
  if (existing) return existing;
  const request = requestJson<CrmTaskDetail>(`/api/v1/crm/tasks/${taskId}`);
  inFlightCrmTaskDetails.set(taskId, request);
  void request.finally(() => {
    if (inFlightCrmTaskDetails.get(taskId) === request) inFlightCrmTaskDetails.delete(taskId);
  }).catch(() => undefined);
  return request;
}

export function createCrmProjectTask(
  projectId: number,
  payload: Partial<CrmTaskRow> & { customer_code: string },
) {
  return requestJson<CrmTaskRow>(`/api/v1/crm/projects/${projectId}/tasks`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateCrmTask(taskId: number, payload: Partial<CrmTaskRow>) {
  return requestJson<CrmTaskRow>(`/api/v1/crm/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function crmFollowupsPage(filters: Record<string, CrmQueryValue> = {}) {
  return requestJson<CrmFollowupPage>(
    `/api/v1/crm/followups/page${crmQuery(filters)}`,
  );
}

export function crmFollowup(followupId: number) {
  return requestJson<CrmFollowupRow>(`/api/v1/crm/followups/${followupId}`);
}

export function createCrmFollowupApprovalDraft(
  payload: CrmFollowupApprovalDraftPayload,
) {
  return requestJson<ApprovalRow>("/api/v1/crm/followups/approval-draft", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createCrmFollowup(
  payload: Partial<CrmFollowupRow> & { project_id: number; task_id: number },
) {
  return requestJson<CrmFollowupRow>("/api/v1/crm/followups", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateCrmFollowup(
  followupId: number,
  payload: Partial<CrmFollowupRow>,
) {
  return requestJson<CrmFollowupRow>(`/api/v1/crm/followups/${followupId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function crmProjectReviews(projectId: number) {
  return requestJson<CrmProjectReviewRow[]>(
    `/api/v1/crm/projects/${projectId}/reviews`,
  );
}

export function createCrmProjectReview(
  projectId: number,
  payload: Partial<CrmProjectReviewRow> = {},
) {
  return requestJson<CrmProjectReviewRow>(
    `/api/v1/crm/projects/${projectId}/reviews`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function updateCrmProjectReview(
  reviewId: number,
  payload: Partial<CrmProjectReviewRow>,
) {
  return requestJson<CrmProjectReviewRow>(`/api/v1/crm/reviews/${reviewId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function approvalsPage(filters: Record<string, CrmQueryValue> = {}) {
  return requestJson<ApprovalPage>(
    `/api/v1/approvals/page${crmQuery(filters)}`,
  );
}

export function myApprovalSubmissionsPage(
  filters: Record<string, CrmQueryValue> = {},
) {
  return requestJson<ApprovalPage>(
    `/api/v1/approvals/my-submissions${crmQuery(filters)}`,
  );
}

export function approval(approvalId: number) {
  return requestJson<ApprovalDetail>(`/api/v1/approvals/${approvalId}`);
}

export function approvedProjectWithdrawalPreview(approvalId: number) {
  return requestJson<ApprovalWithdrawalPreview>(
    `/api/v1/approvals/${approvalId}/withdrawal-preview`,
  );
}

export function withdrawApprovedProject(approvalId: number, reason: string) {
  return requestJson<ApprovalDetail>(
    `/api/v1/approvals/${approvalId}/withdraw-approved`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
  );
}

export function uploadApprovalAttachment(approvalId: number, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<ApprovalAttachmentRow>(
    `/api/v1/approvals/${approvalId}/attachments`,
    {
      method: "POST",
      body: formData,
    },
  );
}

export async function downloadApprovalAttachment(
  approvalId: number,
  attachmentId: number,
) {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(
    `/api/v1/approvals/${approvalId}/attachments/${attachmentId}/download`,
    {
      headers,
      credentials: "include",
    },
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(apiErrorMessage(response.status, text));
  }
  return response.blob();
}

export async function deleteApprovalAttachment(
  approvalId: number,
  attachmentId: number,
) {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(
    `/api/v1/approvals/${approvalId}/attachments/${attachmentId}`,
    {
      method: "DELETE",
      headers,
      credentials: "include",
    },
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(apiErrorMessage(response.status, text));
  }
}

export function createApproval(payload: {
  approval_type: string;
  resource_type?: string;
  resource_id?: string;
  title: string;
  description?: string | null;
  current_handler_user_id?: number | null;
  status?: string;
  priority?: string;
  payload_json?: Record<string, unknown> | unknown[] | null;
  submit?: boolean;
}) {
  return requestJson<ApprovalRow>("/api/v1/approvals", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function submitApproval(
  approvalId: number,
  payload: ApprovalActionPayload = {},
) {
  return requestJson<ApprovalDetail>(`/api/v1/approvals/${approvalId}/submit`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function approveApproval(
  approvalId: number,
  payload: ApprovalActionPayload = {},
) {
  return requestJson<ApprovalDetail>(
    `/api/v1/approvals/${approvalId}/approve`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function rejectApproval(
  approvalId: number,
  payload: ApprovalActionPayload = {},
) {
  return requestJson<ApprovalDetail>(`/api/v1/approvals/${approvalId}/reject`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function requestApprovalSupplement(
  approvalId: number,
  payload: ApprovalActionPayload = {},
) {
  return requestJson<ApprovalDetail>(
    `/api/v1/approvals/${approvalId}/supplement-request`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function supplementApproval(
  approvalId: number,
  payload: ApprovalActionPayload,
) {
  return requestJson<ApprovalDetail>(
    `/api/v1/approvals/${approvalId}/supplement`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function updateApprovalDraft(
  approvalId: number,
  payload: ApprovalDraftUpdatePayload,
) {
  return requestJson<ApprovalDetail>(`/api/v1/approvals/${approvalId}/draft`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function cancelApproval(
  approvalId: number,
  payload: ApprovalActionPayload = {},
) {
  return requestJson<ApprovalDetail>(`/api/v1/approvals/${approvalId}/cancel`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function exceptionSummary(query: { occurrence_type?: ExceptionOccurrenceType } = {}) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null) params.set(key, String(value));
  });
  return requestJson<ExceptionSummary>(`/api/v1/exceptions/summary${params.size ? `?${params.toString()}` : ""}`);
}

export function exceptionCasesPage(query: {
  q?: string;
  domain?: string;
  status?: string;
  severity?: string;
  occurrence_type?: ExceptionOccurrenceType;
  assignment?: ExceptionWorkScope;
  sla_status?: ExceptionSlaFilter;
  rule_code?: string;
  source_batch_kind?: ExceptionSourceBatchKind;
  source_batch_id?: number;
  source_batch_unassigned?: boolean;
  assignee_user_id?: number;
  limit?: number;
  offset?: number;
} = {}) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  return requestJson<ExceptionCasePage>(`/api/v1/exceptions/page?${params.toString()}`);
}

export function exceptionCaseAggregations(query: {
  group_by: ExceptionGroupBy;
  q?: string;
  domain?: string;
  status?: string;
  severity?: string;
  occurrence_type?: ExceptionOccurrenceType;
  assignment?: ExceptionWorkScope;
  sla_status?: ExceptionSlaFilter;
  rule_code?: string;
  source_batch_kind?: ExceptionSourceBatchKind;
  source_batch_id?: number;
  source_batch_unassigned?: boolean;
}, signal?: AbortSignal) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  return requestJson<ExceptionAggregationResponse>(`/api/v1/exceptions/aggregations?${params.toString()}`, { signal });
}

const inFlightExceptionRuleQuality = new Map<string, Promise<ExceptionRuleQualityResponse>>();

function validateExceptionRuleQuality(response: ExceptionRuleQualityResponse) {
  if (!Array.isArray(response.domains) || !Array.isArray(response.rules)) {
    throw new Error("规则质量响应结构无效，请刷新后重试");
  }
  return response;
}

export function exceptionRuleQuality(query: {
  domain?: ExceptionDomain;
  rule_code?: string;
  scan_window_days?: number;
} = {}, signal?: AbortSignal) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  const path = `/api/v1/exceptions/rule-quality${params.size ? `?${params.toString()}` : ""}`;
  if (signal) return requestJson<ExceptionRuleQualityResponse>(path, { signal }).then(validateExceptionRuleQuality);
  const existing = inFlightExceptionRuleQuality.get(path);
  if (existing) return existing;
  const request = requestJson<ExceptionRuleQualityResponse>(path).then(validateExceptionRuleQuality);
  inFlightExceptionRuleQuality.set(path, request);
  void request.finally(() => {
    if (inFlightExceptionRuleQuality.get(path) === request) inFlightExceptionRuleQuality.delete(path);
  }).catch(() => undefined);
  return request;
}

export function exceptionCase(caseNo: string, signal?: AbortSignal) {
  return requestJson<ExceptionCaseDetail>(`/api/v1/exceptions/${encodeURIComponent(caseNo)}`, { signal });
}

export function diagnoseExceptionCase(caseNo: string, force = false) {
  return requestJson<ExceptionDiagnosisJob>(`/api/v1/exceptions/${encodeURIComponent(caseNo)}/diagnoses`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export function exceptionDiagnosisJob(jobId: number, signal?: AbortSignal) {
  return requestJson<ExceptionDiagnosisJob>(`/api/v1/exception-jobs/${jobId}`, { signal });
}

export function retryExceptionDiagnosisJob(jobId: number, reason?: string) {
  return requestJson<ExceptionDiagnosisJob>(`/api/v1/exception-jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
    body: JSON.stringify({ reason: reason?.trim() || null }),
  });
}

export function cancelExceptionDiagnosisJob(jobId: number, reason: string) {
  return requestJson<ExceptionDiagnosisJob>(`/api/v1/exception-jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
    body: JSON.stringify({ reason: reason.trim() }),
  });
}

export function validateExceptionAction(
  caseNo: string,
  actionType: ExceptionActionType,
  parameters: Record<string, unknown> = {},
) {
  return requestJson<ExceptionAction>(`/api/v1/exceptions/${encodeURIComponent(caseNo)}/actions/validate`, {
    method: "POST",
    body: JSON.stringify({ action_type: actionType, parameters }),
  });
}

export function executeExceptionAction(caseNo: string, validationToken: string, idempotencyKey: string) {
  return requestJson<ExceptionAction>(`/api/v1/exceptions/${encodeURIComponent(caseNo)}/actions`, {
    method: "POST",
    body: JSON.stringify({ validation_token: validationToken, idempotency_key: idempotencyKey }),
  });
}

export function exceptionAction(actionId: number) {
  return requestJson<ExceptionAction>(`/api/v1/exception-actions/${encodeURIComponent(actionId)}`);
}

export function assignExceptionCase(caseNo: string, payload: { assignee_user_id?: number | null; due_at?: string | null }) {
  return requestJson<ExceptionCaseItem>(`/api/v1/exceptions/${encodeURIComponent(caseNo)}/assign`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function ignoreExceptionCase(caseNo: string, payload: { reason: string; ignored_until: string }) {
  return requestJson<ExceptionCaseItem>(`/api/v1/exceptions/${encodeURIComponent(caseNo)}/ignore`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function batchAssignExceptionCases(payload: {
  case_nos: string[];
  assignee_user_id?: number | null;
  due_at?: string | null;
}) {
  return requestJson<ExceptionBatchResult>("/api/v1/exceptions/batch/assign", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function batchIgnoreExceptionCases(payload: { case_nos: string[]; reason: string; ignored_until: string }) {
  return requestJson<ExceptionBatchResult>("/api/v1/exceptions/batch/ignore", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function submitExceptionDiagnosisFeedback(
  diagnosisId: number,
  payload: { rating: ExceptionFeedbackRating; note?: string | null },
) {
  return requestJson<ExceptionDiagnosis>(`/api/v1/exception-diagnoses/${encodeURIComponent(diagnosisId)}/feedback`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function verifyExceptionCase(caseNo: string, payload: { note: string; expected_evidence_version: string }) {
  return requestJson<ExceptionVerificationResult>(`/api/v1/exceptions/${encodeURIComponent(caseNo)}/verify`, {
    method: "POST",
    body: JSON.stringify({ note: payload.note.trim(), expected_evidence_version: payload.expected_evidence_version }),
  });
}

export function exceptionOpsSummary(signal?: AbortSignal) {
  return requestJson<ExceptionOpsSummary>("/api/v1/exception-ops/summary", { signal });
}

export function exceptionDiagnosisJobsPage(query: { status?: string; job_kind: "all" | "diagnosis" | "background"; limit?: number; offset?: number }, signal?: AbortSignal) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  return requestJson<ExceptionDiagnosisJobPage>(`/api/v1/exception-jobs/page?${params.toString()}`, { signal });
}

export function exceptionDiagnosisQuality(query: {
  domain?: string;
  rule_code?: string;
  diagnosed_from?: string;
  diagnosed_to?: string;
} = {}) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, value);
  });
  const suffix = params.toString();
  return requestJson<ExceptionDiagnosisQuality>(`/api/v1/exception-diagnoses/quality${suffix ? `?${suffix}` : ""}`);
}

export function exceptionNotifications(limit = 20) {
  return requestJson<ExceptionNotification[]>(`/api/v1/exception-notifications?limit=${limit}`);
}

export function readExceptionNotification(notificationId: number) {
  return requestJson<ExceptionNotification>(`/api/v1/exception-notifications/${notificationId}/read`, {
    method: "POST",
  });
}

export function acknowledgeExceptionNotification(notificationId: number) {
  return requestJson<ExceptionNotification>(`/api/v1/exception-notifications/${notificationId}/acknowledge`, {
    method: "POST",
  });
}

export function exceptionPolicy(signal?: AbortSignal) {
  return requestJson<ExceptionPolicy>("/api/v1/exception-policies", { signal }).then(normalizeExceptionPolicy);
}

export function updateExceptionPolicy(payload: Partial<Omit<ExceptionPolicy, "policy_key" | "updated_at">> & { expected_updated_at: string }) {
  return requestJson<ExceptionPolicy>("/api/v1/exception-policies", {
    method: "PATCH",
    body: JSON.stringify(payload),
  }).then(normalizeExceptionPolicy);
}

export function runExceptionBaselineScan(domain: "crm" | "approval", expectedPolicyUpdatedAt: string) {
  return requestJson<ExceptionBaselineScanResponse>("/api/v1/exceptions/baseline-scan", {
    method: "POST",
    body: JSON.stringify({
      domain,
      expected_policy_updated_at: expectedPolicyUpdatedAt,
    }),
  });
}

export function controlledActionCatalog() {
  return requestJson<ControlledActionCatalogItem[]>("/api/v1/ai/actions/catalog");
}

export function controlledActionProposals(query: {
  domain?: string;
  review_status?: "pending" | "accepted" | "rejected";
  limit?: number;
  offset?: number;
} = {}, signal?: AbortSignal) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  const suffix = params.toString();
  return requestJson<ControlledActionProposalPage>(`/api/v1/ai/actions/proposals${suffix ? `?${suffix}` : ""}`, { signal });
}

export function controlledActionProposal(proposalNo: string, signal?: AbortSignal) {
  return requestJson<ControlledActionProposal>(`/api/v1/ai/actions/proposals/${encodeURIComponent(proposalNo)}`, { signal });
}

export function controlledActionExecutions(query: {
  domain?: string;
  status?: "pending" | "completed" | "failed" | "cancelled";
  limit?: number;
  offset?: number;
} = {}, signal?: AbortSignal) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  const suffix = params.toString();
  return requestJson<ControlledActionExecutionPage>(`/api/v1/ai/actions/executions${suffix ? `?${suffix}` : ""}`, { signal });
}

export function validateControlledExceptionAction(
  caseNo: string,
  actionType: ControlledExceptionActionType,
  parameters: Record<string, unknown> = {},
) {
  return requestJson<ControlledActionValidation>(`/api/v1/ai/actions/exceptions/${encodeURIComponent(caseNo)}/validate`, {
    method: "POST",
    body: JSON.stringify({ action_type: actionType, parameters }),
  });
}

export function executeControlledAction(proposalNo: string, payload: {
  expected_updated_at: string;
  confirmation: true;
  idempotency_key: string;
  validation_token?: string | null;
}) {
  return requestJson<ControlledActionExecution>(`/api/v1/ai/actions/proposals/${encodeURIComponent(proposalNo)}/execute`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function reviewControlledCrmAction(proposalNo: string, payload: {
  expected_updated_at: string;
  confirmation: true;
  decision: "accept" | "reject" | "task";
  idempotency_key: string;
  note?: string | null;
}) {
  return requestJson<ControlledActionExecution>(`/api/v1/ai/actions/proposals/${encodeURIComponent(proposalNo)}/crm-review`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
