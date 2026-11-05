import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const app = fs.readFileSync(path.join(frontendRoot, "src", "App.tsx"), "utf8").replace(/\r\n/g, "\n");
const client = fs.readFileSync(path.join(frontendRoot, "src", "api", "client.ts"), "utf8").replace(/\r\n/g, "\n");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

for (const route of [
  "/api/v1/exceptions/summary",
  "/api/v1/exceptions/page",
  "/api/v1/exceptions/aggregations",
  "/api/v1/exceptions/batch/assign",
  "/api/v1/exceptions/batch/ignore",
  "/api/v1/exception-diagnoses/",
  "/api/v1/exception-diagnoses/quality",
  "/api/v1/exception-jobs/",
  "/api/v1/exception-jobs/page",
  "/api/v1/exception-ops/summary",
  "/api/v1/exception-actions/",
  "/api/v1/exception-notifications",
  "/api/v1/exception-policies"
]) {
assert(client.includes(route), `Exception API client must include ${route}`);
}
assert(/export type ExceptionAction = \{\r?\n\s+id: number;/.test(client), "Exception actions must retain their numeric status-query ID");
assert(client.includes("ai_enabled: boolean;") && client.includes("actions_enabled: boolean;"), "Exception summary must expose independent AI and action capabilities");
assert(client.includes("manual_ai_enabled: boolean;") && client.includes("scheduled_ai_enabled: boolean;") && client.includes("full_scan_enabled: boolean;") && client.includes("digest_enabled: boolean;"), "Exception summary and policy contracts must expose independently controlled workflows");
assert(client.includes('export type ExceptionOccurrenceType = "baseline" | "new" | "reopened";'), "Exception cases must expose baseline, new, and reopened occurrence types");
assert(client.includes("occurrence_cycle?: number | null;") && client.includes("rule_version?: string | null;"), "Exception cases must remain backward compatible while exposing occurrence cycles and rule versions");
assert(client.includes("by_occurrence: Record<string, number>;"), "Exception summaries must expose occurrence counts");
assert(client.includes("batchAssignExceptionCases") && client.includes("batchIgnoreExceptionCases"), "Exception client must expose batch assignment and ignore operations");
assert(client.includes("submitExceptionDiagnosisFeedback"), "Exception client must expose diagnosis feedback");

for (const permission of [
  "exception_center.view",
  "exception_center.diagnose",
  "exception_center.manage",
  "exception_center.action_execute",
  "exception_center.policy_manage"
]) {
  assert(app.includes(permission), `Exception center must enforce ${permission}`);
}

assert(app.includes('if (path.startsWith("/exceptions")) return "exceptions";'), "Exception center route must be addressable");
assert(app.includes('page: "exceptions", label: "异常中心"'), "Exception center must appear in global navigation");
assert(app.includes("VITE_EXCEPTION_CENTER_ENABLED"), "Exception center UI must honor its build-time feature flag");
assert(app.includes('import.meta.env.VITE_EXCEPTION_CENTER_ENABLED ?? "true"'), "Released exception center UI must remain visible when the optional build flag is omitted");
assert(app.includes("item.enabled !== false"), "Disabled feature navigation must be inaccessible without API calls");
assert(app.includes('!actionPath.startsWith("/exceptions") || EXCEPTION_CENTER_UI_ENABLED'), "Disabled exception routes must not be offered as API-error action links");
assert(app.includes("function ExceptionCenterPage"), "Exception center page must exist");
assert(app.includes("function ExceptionCaseDrawer"), "Exception detail drawer must exist");
assert(app.includes('const canDiagnose = aiEnabled && hasPermission(permissions, "exception_center.diagnose");'), "Diagnosis controls must require both the backend capability and diagnose permission");
assert(app.includes('const canSubmitFeedback = hasPermission(permissions, "exception_center.diagnose");'), "Diagnosis feedback must remain available when AI generation is disabled");
assert(app.includes('const canExecute = actionsEnabled && hasPermission(permissions, "exception_center.action_execute") && availableActionTypes.length > 0 && Boolean(caseStatus'), "Action controls must require backend capability, exception permission, source permission, and an actionable case status");
assert(app.includes("aiEnabled={summaryData?.ai_enabled === true}") && app.includes("actionsEnabled={summaryData?.actions_enabled === true}"), "Missing or failed exception summaries must disable AI and action controls");
for (const [key, label, minimum] of [
  ["ai_daily_limit", "每日模型调用上限（0 为不限量）", 0],
  ["ai_batch_limit", "单批诊断上限", 1],
  ["manual_ai_daily_limit", "人工诊断每日上限（0 为不限量）", 0],
  ["scheduled_ai_daily_limit", "定时诊断每日上限（0 为不限量）", 0],
  ["scheduled_ai_batch_limit", "定时诊断单批上限", 1],
  ["ai_concurrency", "模型并发数", 1],
  ["stale_diagnosis_hours", "诊断失效小时数", 1]
]) {
  assert(app.includes(`["${key}", "${label}", ${minimum}]`), `Exception policy must enforce the backend minimum for ${key}`);
}
assert(app.includes("min={min}"), "Exception policy inputs must apply their field-specific minimum");
assert(app.includes("function ExceptionDiagnosisProgress") && app.includes('role="progressbar"'), "Active diagnoses must expose an accessible progress indicator");
assert(app.includes('summaryData.manual_budget.unlimited ? "不限量"'), "Unlimited diagnosis usage must be labeled clearly");
assert(app.includes("function ExceptionDashboardSummary"), "Dashboard must expose exception summary");
assert(app.includes("exceptionDiagnosisJob(job.id, controller.signal)"), "Diagnosis jobs must be polled with request cancellation");
assert(app.includes("exceptionOverview.open + exceptionOverview.action_required + exceptionOverview.processing + exceptionOverview.blocked"), "Notification panel must count every active exception status");
assert(app.includes('const canViewExceptions = EXCEPTION_CENTER_UI_ENABLED && hasPermission(permissions, "exception_center.view");'), "Exception notifications must require the feature flag and view permission");
assert(client.includes("acknowledgeExceptionNotification"), "Exception notifications must expose independent acknowledgement");
assert(app.includes("确认已知晓"), "Exception notifications must let users acknowledge high-risk alerts");
assert(app.includes("detail.diagnosis?.evidence_version === detail.evidence_version"), "Case detail must reject diagnoses from stale evidence versions");
assert(app.includes("detail.diagnoses.find((item) => item.evidence_version === detail.evidence_version)"), "Case detail may only fall back to diagnosis history for the current evidence version");
assert(app.includes("submitExceptionDiagnosisFeedback(latestDiagnosis.id") && app.includes('data-testid="exception-feedback-saved"'), "Current-evidence diagnoses must support visible saved feedback");
assert(app.includes("current?.evidence_version === next.evidence_version ? current : null"), "Action validation must be discarded when case evidence changes");
const verifyCaseStart = app.indexOf("const verifyCase = async () => {");
const verifyCaseEnd = app.indexOf("\n  return (", verifyCaseStart);
const verifyCaseBody = app.slice(verifyCaseStart, verifyCaseEnd);
assert(verifyCaseStart >= 0 && verifyCaseEnd > verifyCaseStart && verifyCaseBody.includes("const refreshed = await exceptionCase(caseNo);"), "Verification must fetch the complete current case after the backend scan finishes");
assert(!verifyCaseBody.includes("setDetail(result.case)") && !verifyCaseBody.includes("...result.case"), "Verification must never merge the summary response into stale detail evidence");
assert(app.includes("validateExceptionAction(caseNo, actionType)"), "Actions must be validated before execution");
assert(app.includes("validation.validation_token"), "Execution must require a validation token");
assert(client.includes("export function exceptionAction(actionId: number)"), "Action status queries must use the backend's numeric action ID");
assert(app.includes("exceptionAction(actionResult.id)"), "Running actions must poll the status endpoint by action ID");
assert(app.includes("定位原始记录"), "Case detail must expose its source deep link");
assert(app.includes('const [query, setQuery] = useState(() => initialQueryParam("q"));\n  const [typeFilter, setTypeFilter] = useState(() => initialQueryParam("result_type") || initialQueryParam("type"));'), "Inventory check deep links must initialize q and result_type filters");
assert(app.includes('const urlKind = (initialQueryParam("kind") || initialQueryParam("tab")) as MasterKind;'), "Legacy master-data exception links must still select their target record type");
assert(app.includes("exceptionActionSourcePermissions"), "Exception actions must declare their source-module permissions");
assert(app.includes('hasPermission(permissions, exceptionActionSourcePermissions[value])'), "Exception actions must require both exception and source-module permissions");
assert(app.includes('row.assignee_name ?? row.assignee_user_id ?? "未分派"'), "Exception lists must show the assignee name when the API provides it");
assert(app.includes('initialQueryParam("occurrence_type")') && app.includes("occurrence_type: occurrenceType || undefined"), "Occurrence filters must initialize from and be sent through the exact URL/API parameter");
assert(app.includes("exceptionOccurrenceDescriptions.baseline") && app.includes("exceptionOccurrenceDescriptions.reopened"), "Occurrence filters must explain baseline, new, and reopened semantics");
assert(app.includes('["规则版本", detail.rule_version ?? "未标记"]') && app.includes('["发生周期", detail.occurrence_cycle != null'), "Exception detail must show its rule version and occurrence cycle");
assert(app.includes('data-testid={`exception-summary-${item.status ?? "all"}`}') && app.includes("updateFilters({ status: item.status ?? \"\" })"), "Summary metrics must apply exact list status filters");
assert(app.includes('aria-label="选择当前页全部案件"') && app.includes("toggleCurrentPage"), "Exception lists must support current-page selection");
assert(app.includes("<ExceptionBatchActions") && app.includes("completeBatchAction"), "Selected exceptions must expose batch actions and refresh after completion");
assert(app.includes("恢复默认自动分派") && app.includes("按 SLA 重新计算"), "Batch reset controls must describe restored system defaults instead of permanent clearing");
assert(app.includes("payload.assignee_user_id = null") && app.includes("payload.due_at = null"), "Batch default restoration must continue sending explicit null values");
assert(app.includes('const exceptionBatchAssignableStatuses: ExceptionCaseStatus[] = ["open", "action_required", "processing", "blocked"]'), "Resolved and ignored exceptions must not be selectable for batch workflows");
assert(app.includes('const exceptionBatchIgnoreableStatuses: ExceptionCaseStatus[] = ["open", "action_required", "blocked"]'), "Processing exceptions must not be eligible for batch ignore");
assert(app.includes('data-testid="exception-batch-ignore-blocked"'), "Mixed processing selections must explain why batch ignore is unavailable");
assert(app.includes('data-testid="exception-summary-error"') && app.includes('data-testid="exception-list-error"'), "Summary and list failures must be isolated");
assert(app.includes('data-testid="exception-empty-state"') && app.includes("listLoading && !pageData"), "Exception center must expose explicit loading and empty states");
assert(client.includes('export type ExceptionWorkScope = "mine" | "assigned" | "unassigned";'), "Assignment filters must use the backend ownership contract");
assert(client.includes('export type ExceptionSlaFilter = "overdue" | "due_soon" | "on_track" | "no_due_date";'), "SLA filters must use the backend status contract");
assert(app.includes("assignment: workScope || undefined") && app.includes("sla_status: slaFilter || undefined"), "Quick filters must send exact assignment and sla_status parameters");
assert(app.includes('data-testid="exception-quick-mine"') || app.includes('data-testid={`exception-quick-${item.key}`}'), "The exception center must expose quick work-queue filters");
assert(app.includes("exceptionCaseAggregations({ ...filters, group_by: groupBy })"), "Grouped views must call the independent aggregation endpoint with the same filters as the case page");
const pageClientStart = client.indexOf("export function exceptionCasesPage");
const pageClientEnd = client.indexOf("export function exceptionCaseAggregations");
assert(pageClientStart >= 0 && pageClientEnd > pageClientStart && !client.slice(pageClientStart, pageClientEnd).includes("group_by"), "The paginated case endpoint must remain pure pagination");
const aggregationClientStart = client.indexOf("export function exceptionCaseAggregations");
const aggregationClientEnd = client.indexOf("export function exceptionCase(", aggregationClientStart);
assert(aggregationClientStart >= 0 && aggregationClientEnd > aggregationClientStart && client.slice(aggregationClientStart, aggregationClientEnd).includes("q?: string"), "The aggregation endpoint must expose the shared q parameter");
assert(app.includes('data-testid="exception-aggregation-search-scope"') && app.includes("聚合结果基于当前全部筛选条件，包含关键词"), "Grouped views must explain that every active filter, including q, affects aggregation results");
for (const domain of ["inventory", "receivable", "master_data", "import"]) {
  assert(app.includes(`${domain}: [`), `Structured business evidence must cover ${domain}`);
}
assert(app.includes('data-testid={`exception-business-evidence-${domain}`}'), "Business evidence must expose a stable test target");
for (const [code, label] of [
  ["true_negative_stock", "真实负库存"],
  ["missing_purchase", "采购记录缺失"],
  ["duplicate_sale", "销售记录重复"],
  ["warehouse_mismatch", "仓库归属不一致"],
  ["warehouse_missing", "仓库信息缺失"],
  ["unit_conversion_error", "单位换算错误"],
  ["stale_snapshot", "库存快照过期"],
  ["import_error", "导入数据错误"],
  ["snapshot_mismatch", "库存快照不一致"],
  ["missing_product_master", "商品主数据缺失"],
  ["amount_mismatch", "应收金额不一致"],
  ["missing_counterparty", "往来单位缺失"],
  ["duplicate_record", "重复业务记录"],
  ["stale_data", "数据已过期"],
  ["master_data_mismatch", "主数据匹配不一致"],
  ["missing_customer_master", "客户主数据缺失"],
  ["missing_supplier_master", "供应商主数据缺失"],
  ["role_mismatch", "业务角色不一致"],
  ["incomplete_master_data", "主数据字段不完整"],
  ["duplicate_import", "重复导入"],
  ["invalid_rows", "导入行校验失败"],
  ["uncommitted_batch", "导入批次未提交"],
  ["insufficient_evidence", "证据不足"]
]) {
  assert(app.includes(`${code}: "${label}"`), `Root cause ${code} must have the Chinese label ${label}`);
}
assert(app.includes("function hasExceptionEvidencePath") && app.includes("field.paths.some((path) => hasExceptionEvidencePath(source, path))"), "Explicit null evidence fields must remain distinguishable from unmapped evidence");
assert(app.includes("const hasMappedEvidence =") && app.includes("field.mapped") && app.includes("if (!hasMappedEvidence)"), "Completely unmapped evidence must retain the generic fallback");
assert(app.includes("field.value !== undefined || field.expected") && app.includes('data-evidence-missing={field.missing ? "true" : undefined}'), "Missing expected evidence must remain visible and expose warning state");
assert(app.includes('field.missing ? "rounded-md border border-amber-300 bg-amber-50 px-3 py-2"') && app.includes('return "未提供"'), "Missing expected evidence must render a clear warning and the 未提供 fallback");
assert(app.includes('data-testid="exception-diagnosis-structured"') && app.includes("diagnosis.root_cause_code") && app.includes("diagnosis.recommended_steps"), "AI diagnosis must render the structured result instead of raw JSON");
assert(app.includes("setJob(next.active_diagnosis_job ?? null)") && app.includes("exceptionDiagnosisJob(job.id, controller.signal)"), "Active diagnosis jobs must recover from case detail and continue cancellable polling");
assert(app.includes('const canPollDiagnosisJob = hasPermission(permissions, "exception_center.diagnose");') && app.includes('if (!canPollDiagnosisJob || !job'), "Active diagnosis polling must not issue unauthorized job-detail requests");
const diagnosisPollingStart = app.indexOf('if (!canPollDiagnosisJob || !job || ["completed", "failed", "cancelled"].includes(job.status)) return;');
const diagnosisPollingEnd = app.indexOf("\n  useEffect(() => {\n    if (!actionResult", diagnosisPollingStart);
const diagnosisPollingBody = app.slice(diagnosisPollingStart, diagnosisPollingEnd);
assert(diagnosisPollingStart >= 0 && diagnosisPollingEnd > diagnosisPollingStart && diagnosisPollingBody.includes("status === 403 || status === 404") && diagnosisPollingBody.includes("onPermissionsRefresh()") && diagnosisPollingBody.includes("exceptionCase(caseNo, controller.signal)"), "403/404 polling failures must stop and refresh permissions plus cancellable case detail");
assert(diagnosisPollingBody.includes("Math.min(30_000, 2_000 * (2 ** (consecutiveFailures - 1)))") && diagnosisPollingBody.includes("schedule(retryDelay)"), "Network and 5xx polling failures must use capped exponential backoff");
assert(app.includes('data-testid="exception-job-poll-issue"') && app.includes("立即重试状态刷新") && app.includes("setJobPollRetryKey((value) => value + 1)"), "Polling failures must be visible and expose an immediate manual retry");
assert(app.includes('data-testid="exception-verify-note"') && app.includes("verifyNote.trim().length < 2"), "Verification must require an auditable note");
assert(app.includes("expected_evidence_version: detail.evidence_version"), "Verification must reject stale evidence by submitting the current evidence version");
assert(client.includes("payload: { note: string; expected_evidence_version: string }"), "The client must require an evidence version for verification");
assert(app.includes('data-testid="exception-verification-result"') && app.includes('const snapshots = [["复检前", result.before], ["复检后", result.after]]'), "Verification must display deterministic before and after snapshots");
assert(app.includes("withExceptionReturnContext(detail.action_path, caseNo)") && app.includes('data-testid="exception-return-context"') && app.includes('params.set("return_case", caseNo)'), "Source deep links must preserve the exception return context");
assert(app.includes('data-testid="exception-operations-panel"') && app.includes('label: "AI Worker"'), "Operations must display the AI worker independently");
assert(client.includes("export type ExceptionCircuitStatus = {") && client.includes("consecutive_failures: number;") && client.includes("retry_after_seconds: number;") && client.includes("stale: boolean;") && client.includes('source: "ai_worker";') && client.includes("circuit: ExceptionCircuitStatus | null;"), "Operations must use the nullable strong circuit status contract");
assert(app.includes('data-testid="exception-circuit-status"') && app.includes("circuit.consecutive_failures") && app.includes("circuit.retry_after_seconds") && app.includes("circuit.stale") && app.includes("circuit.source"), "Operations must render every circuit status signal");
assert(app.includes('circuit == null ? "unavailable"') && app.includes('circuit.stale ? "stale"') && app.includes('data-circuit-state={circuitState}'), "Null and stale circuit reports must never render as healthy");
assert(!app.includes("circuit.state") && !app.includes("circuit.status") && !app.includes("circuit.open_until"), "Operations must not read retired circuit fields");
const operationsStart = app.indexOf("function ExceptionOperationsPanel");
const operationsEnd = app.indexOf("function ExceptionDiagnosisQualityPanel", operationsStart);
const operationsBody = app.slice(operationsStart, operationsEnd);
assert(operationsStart >= 0 && operationsEnd > operationsStart && operationsBody.includes('exceptionDiagnosisJobsPage({ ...jobQuery, job_kind: jobKind || "all" }, controller.signal)'), "The all-jobs view must use the backend's cancellable unified queue contract");
assert((operationsBody.match(/exceptionDiagnosisJobsPage\(/g) ?? []).length === 1 && !operationsBody.includes('job_kind: "diagnosis"') && !operationsBody.includes('job_kind: "background"'), "The all-jobs view must not fetch, merge, or slice two independent queues");
assert(operationsBody.includes("offset: jobOffset") && operationsBody.includes("setJobOffset(jobOffset + jobLimit)") && operationsBody.includes('data-testid="exception-job-pagination"'), "Operations jobs must use real server offset pagination");
assert(app.includes('job.job_kind === "diagnosis" && ["failed", "cancelled"].includes(job.status)') && app.includes('job.job_kind === "diagnosis" && ["queued", "processing"].includes(job.status)'), "Diagnosis-only write controls must never appear for background jobs");
assert(app.includes('const canManagePolicy = hasPermission(permissions, "exception_center.policy_manage");') && app.includes("const canOperateJobs = canManagePolicy;"), "Job retry and cancellation must require exception policy-manage permission");
assert(app.includes("const canReadJobs = canManagePolicy;"), "Global job reads must require exception policy-manage permission");
assert(operationsBody.includes('if (!canManagePolicy) {\n      loadControllerRef.current = null;\n      setSummaryData(null);') && app.includes('function ExceptionDiagnosisQualityPanel({ permissions }') && app.includes('if (!canManagePolicy) {\n      setData(null);'), "Operations and quality APIs must be gated before requests are issued");
assert(app.includes('policyOpen && canManagePolicy ? <ExceptionPolicyDrawer permissions={permissions}') && app.includes('if (!form || !originalForm || !canManagePolicy || !hasChanges) return;'), "Policy reads and writes must remain behind policy-manage permission and reject empty updates");
assert(client.includes("export function exceptionPolicy(signal?: AbortSignal)") && app.includes("exceptionPolicy(controller.signal)"), "Policy reads must support request cancellation");
assert(app.includes("loadSequenceRef.current") && app.includes("loadControllerRef.current?.abort()"), "Policy reads must reject stale responses when the drawer reloads or unmounts");
assert(app.includes('data-testid="exception-job-cancel-reason"') && app.includes("cancelReason.trim().length < 2"), "Job cancellation must require an audit reason");
assert(app.includes('data-testid="exception-diagnosis-quality"') && app.includes("evidence_reference_valid_rate") && app.includes("qualityRules") && app.includes("usage_completeness_rate") && app.includes("usage_missing_count"), "Diagnosis quality must expose feedback, evidence validity, usage completeness, and rule-level quality");
const qualityClientStart = client.indexOf("export function exceptionDiagnosisQuality");
const qualityClientEnd = client.indexOf("export function exceptionNotifications", qualityClientStart);
const qualityClientBody = client.slice(qualityClientStart, qualityClientEnd);
assert(qualityClientStart >= 0 && qualityClientEnd > qualityClientStart && qualityClientBody.includes("diagnosed_from?: string") && qualityClientBody.includes("diagnosed_to?: string") && qualityClientBody.includes("new URLSearchParams()"), "Diagnosis quality API must pass both diagnosis time filters");
assert(app.includes('type="datetime-local"') && app.includes("diagnosed_from: start?.toISOString()") && app.includes("diagnosed_to: end?.toISOString()") && app.includes("诊断开始时间不能晚于结束时间"), "Diagnosis quality UI must validate and serialize the selected local time range");
for (const category of ["根因错误", "证据不足", "步骤不可执行", "建议有风险", "表达不清"]) {
  assert(app.includes(category), `Diagnosis feedback must offer the ${category} category`);
}
assert(app.includes("parseExceptionFeedbackNote") && app.includes("serializeExceptionFeedbackNote") && app.includes("[问题分类："), "Diagnosis feedback must round-trip its category through the existing note field");
assert(app.includes('feedbackRating === "partial" || feedbackRating === "incorrect"') && app.includes("feedbackNote.trim().length >= 2") && app.includes("disabled={!feedbackCanSave"), "Partial and incorrect feedback must require a category and a two-character explanation");
assert(app.includes("EXCEPTION_FEEDBACK_NOTE_MAX_LENGTH - prefix.length") && app.includes("maxLength={feedbackNoteMaxLength}") && app.includes("exceptionFeedbackExplanationMaxLength(category || undefined)"), "Serialized diagnosis feedback must stay within the backend 2000-character note limit");
assert(app.includes('type ExceptionCenterView = "cases" | "actions" | "operations" | "quality"') && app.includes("canOpenCenterView(centerView)") && app.includes("fallbackCenterView"), "Unauthorized exception-center views must fall back to the first permission-scoped view");
assert(app.includes("<ExceptionAiChat") && app.includes('path: "/exceptions?assistant=open"') && !app.includes('key: "ai" as const, label: "AI 协同"'), "The streaming AI chat must replace the legacy exception-center AI tab");
assert(app.includes('label: "受控动作"') && app.includes("<ControlledActionCenter permissions={permissions} navigate={navigate} />"), "The controlled action center must be an exception-center view");
assert(app.includes('exceptionOverview?.ai_chat_enabled === true && hasPermission(permissions, "exception_center.view") && hasPermission(permissions, "crm_insight.view")'), "Streaming AI visibility must require the runtime flag and both fine-grained permissions");
assert(client.includes("ai_case_analysis_enabled: boolean") && app.includes('summaryData?.ai_case_analysis_enabled === true'), "Case AI entry must require the server feature flag");
assert(app.includes('operation: "exception.case_analysis"') && app.includes('message: "分析该异常发生的原因，并给出可验证的解决方案"'), "Case AI entry must launch the fixed server-scoped analysis operation");
assert(app.includes('context: { scope: "case", filters: {}, case_nos: [row.case_no] }') && !app.includes("evidence: row.evidence"), "Case AI requests must send only the case identifier, never evidence content");
assert(app.includes('const canViewActions = hasAnyPermission(permissions, ["crm_insight.review", "exception_center.action_execute"]);'), "Controlled actions must use the existing fine-grained review or execute permissions");
assert(app.includes('data-testid="controlled-action-confirm"') && app.includes("confirmation: true") && app.includes("window.confirm"), "Controlled actions must require an explicit second human confirmation");
assert(app.includes("expected_updated_at: proposal.updated_at") && app.includes("reason.status === 409") && app.includes("controlledActionProposal(proposalNo)"), "Controlled action CAS conflicts must refresh the proposal before retry");
assert(app.includes("controlledActionIdempotencyKey()") && app.includes("idempotency_key: idempotencyKey"), "Controlled action execution must submit a stable per-dialog idempotency key");
assert(app.includes("setValidation(null)") && app.includes("关闭弹窗后立即丢弃"), "High-risk validation tokens must remain ephemeral UI state");
for (const endpoint of ["/api/v1/ai/actions/catalog", "/api/v1/ai/actions/proposals", "/api/v1/ai/actions/executions", "/api/v1/ai/actions/exceptions/"]) {
  assert(client.includes(endpoint), `Controlled action client must include ${endpoint}`);
}
for (const parameter of ["date_from", "date_to", "warehouse_name", "product_code", "anomaly_type"]) {
  assert(app.includes(`useState(() => initialQueryParam("${parameter}"))`), `Inventory flow deep links must initialize ${parameter}`);
}
assert(app.includes('const [resultType, setResultType] = useState(() => initialQueryParam("result_type"));'), "Receivable check deep links must initialize result_type");
assert((app.match(/useState\(\(\) => initialQueryParam\("q"\)\)/g) ?? []).length >= 2, "Inventory and receivable checks must initialize search deep links");
assert(app.includes("当前筛选范围没有异常案件"), "Exception center must provide an empty state");
assert(app.includes('function normalizeExceptionQuery(value: string)') && app.includes('value.normalize("NFKC").replace(/\\s+/g, " ").trim().slice(0, 200)'), "Exception search must normalize Unicode and whitespace and cap the API value at 200 characters");
assert(app.includes('placeholder="搜索案件编号、规则、对象或原因" maxLength={200}'), "Exception search input must enforce the 200-character browser limit");
assert(client.includes("source_batch_unassigned?: boolean;") && app.includes("source_batch_unassigned: sourceBatchUnassigned || undefined"), "Exception page and aggregation clients must support the unassigned-batch contract");
assert(client.includes('export type ExceptionSourceBatchKind = "import" | "inventory_check" | "legacy";') && client.includes("source_batch_kind?: ExceptionSourceBatchKind;"), "Batch filters must use a typed namespace instead of a bare integer ID");
assert(app.includes("const conflictingBatch =") && app.includes("const orphanBatchId =") && app.includes("source_batch_kind: conflictingBatch || invalidBatchKind ? null"), "Invalid or conflicting initial batch URL state must be normalized before API calls");
assert(app.includes('data-testid="exception-unassigned-batch-filter"') && app.includes('row.key === "unassigned" ? { sourceBatchKind: "", sourceBatchId: "", sourceBatchUnassigned: true, groupBy: "" }'), "Unassigned batch drill-down must clear both typed batch fields");
assert(app.includes("sourceBatchKind: row.source_batch_kind") && app.includes("sourceBatchId: String(row.source_batch_id"), "Typed batch aggregation drill-down must send both namespace and ID");
assert(client.includes("total: number;") && client.includes("truncated: boolean;") && app.includes('data-testid="exception-aggregation-truncated"'), "Aggregation truncation must be explicit in both the API contract and UI");
const policyClientStart = client.indexOf("export function updateExceptionPolicy");
const policyClientEnd = client.indexOf("\n}", policyClientStart);
assert(policyClientStart >= 0 && client.slice(policyClientStart, policyClientEnd).includes('method: "PATCH"'), "Policy updates must use partial PATCH semantics");
assert(app.includes("ApiErrorNotice"), "Structured API errors must be visible in the UI");
assert(client.includes('export const API_ERROR_EVENT = "project-base:api-error";'), "Structured API errors must use the shared global event channel");
assert(client.includes("error.status === 401") && client.includes('path.startsWith("/api/v1/auth/")'), "Authentication failures must not create global API error noise");
assert(app.includes("window.addEventListener(API_ERROR_EVENT, handleApiError)"), "The application root must subscribe to global structured API errors");
assert(app.includes('data-testid="global-api-error"') && app.includes('data-testid="api-error-close"'), "Global API error notices must be visible and dismissible");
assert(!app.includes("/inventory?inventory_status=abnormal"), "Inventory anomaly links must use attention filters");
assert(app.includes("/inventory?attention_state=needs_attention"), "Inventory anomaly links must open the effective filter");
assert(!app.match(/\["stock_qty",\s*"账面数量",\s*"number"\]/), "Upstream stock quantity must not be editable");
assert(app.includes("该数量来自上游进销存，只读展示"), "Inventory edit view must explain upstream correction authority");

console.log("Exception center assertions passed.");
