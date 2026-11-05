import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const app = fs.readFileSync(path.join(frontendRoot, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(frontendRoot, "src", "api", "client.ts"), "utf8");
const e2e = fs.readFileSync(path.join(frontendRoot, "e2e", "exception-crm-approval-stage4.spec.ts"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(
  client.includes('export type ExceptionDomain = "inventory" | "receivable" | "master_data" | "import" | "system" | "crm" | "approval";'),
  "ExceptionDomain must include CRM and approval without removing existing domains"
);
assert(client.includes("diagnosis_supported?: boolean;"), "Exception cases must expose the optional diagnosis_supported capability");
assert(client.includes('export type ExceptionDomainMode = "off" | "shadow" | "visible";'), "Exception rollout modes must be closed, shadow, or visible");
assert(client.includes("domain_modes: ExceptionDomainModes;"), "Exception policy must expose CRM and approval domain modes");
assert(app.includes('crm: "客户 CRM"') && app.includes('approval: "审批"'), "CRM and approval domains must have user-facing labels");

assert(app.includes("function initialPositiveQueryId(name: string)"), "Object deep links must reject malformed and non-positive IDs");
for (const parameter of ["task_id", "followup_id", "approval_id"]) {
  assert(app.includes(`initialPositiveQueryId("${parameter}")`), `Deep links must parse ${parameter} with the positive-ID guard`);
  assert(app.includes(`replaceCurrentQueryParams({ ${parameter}: null })`), `Closing ${parameter} detail must remove only that object parameter`);
}
assert(app.includes("void crmTaskDetail(requestedTaskId)"), "Task deep links must fetch the exact task outside the current page");
assert(app.includes("void crmFollowup(selectedFollowupId)"), "Follow-up deep links must fetch the exact follow-up outside the current page");
assert(app.includes('const requestedApprovalId = initialPositiveQueryId("approval_id");') && app.includes("const canViewApprovals = canListApprovals || Boolean(requestedApprovalId);"), "Approval deep links must parse an exact object ID while list access remains separately permission-gated");
assert(app.includes("if (!canView || !selectedFollowupId)"), "Follow-up deep links must not issue detail requests without view permission");
assert(app.includes("if (!canView || !requestedTaskId)"), "Task deep links must not issue detail requests without view permission");
assert(app.includes("<CrmModulePage key={locationKey}"), "Same-path query changes must remount CRM state from the new URL");

assert(app.includes("withExceptionReturnContext(detail.action_path, caseNo)"), "Source links must attach the exception return context");
assert(app.includes('params.set("return_to", `${window.location.pathname}${window.location.search}`);'), "Source links must preserve the exact exception URL");
assert(app.includes('params.set("return_case", caseNo);'), "Source links must preserve the case number");
assert(app.includes('data-testid="exception-return-context"') && app.includes("返回异常案件"), "Source pages must expose an explicit return action");

for (const kind of ["crm_task_close_state", "crm_followup_binding", "approval_terminal_integrity"]) {
  assert(e2e.includes(kind) || app.includes(kind), `Stage-four evidence must cover ${kind}`);
}
for (const field of [
  "task_id",
  "task_code",
  "project_id",
  "customer_code",
  "followup_id",
  "followup_task_id",
  "followup_project_id",
  "followup_customer_code",
  "task_project_id",
  "task_customer_code",
  "approval_id",
  "reviewed_at",
  "closed_at",
  "latest_state_event_id",
  "latest_state_event_status",
  "latest_state_event_at"
]) {
  assert(app.includes(`"${field}"`) || e2e.includes(`${field}:`), `Stage-four evidence mapping must include ${field}`);
}
assert(app.includes('data-testid={`exception-business-evidence-${domain}`}'), "Structured CRM and approval evidence must retain a stable test target");

assert(app.includes("const diagnosisSupported = detail?.diagnosis_supported !== false;"), "Missing capability must stay backward compatible while explicit false fails closed");
assert(app.includes("const canStartDiagnosis = canDiagnose && diagnosisSupported && !caseClosed;"), "Diagnosis UI must require global AI capability, permission, domain support, and an open case");
const diagnoseStart = app.indexOf("const diagnose = async () => {");
const diagnoseEnd = app.indexOf("\n  const mutateJob", diagnoseStart);
assert(diagnoseStart >= 0 && diagnoseEnd > diagnoseStart && app.slice(diagnoseStart, diagnoseEnd).includes("if (!canStartDiagnosis) return;"), "The diagnosis handler must repeat the UI capability gate");
assert(app.includes("const canRetryDiagnosisJob = diagnosisSupported") && app.includes('data-testid="exception-job-retry"'), "Unsupported domains must hide diagnosis job retry controls");
const mutateStart = app.indexOf('const mutateJob = async (mode: "retry" | "cancel") => {');
const mutateEnd = app.indexOf("\n  const validateAction", mutateStart);
const mutateBody = app.slice(mutateStart, mutateEnd);
assert(mutateStart >= 0 && mutateEnd > mutateStart && mutateBody.includes('if (mode === "retry" && !diagnosisSupported) return;'), "The retry handler must fail closed for unsupported domains");
assert(app.includes('(job.cancellable || ["queued", "processing"].includes(job.status)) && canManagePolicy'), "Unsupported active jobs must remain cancellable by policy managers");
assert(app.includes('data-testid="exception-diagnosis-unsupported"') && app.includes("CRM 与审批异常暂不支持智能诊断"), "Unsupported domains must explain deterministic-only handling");

assert(app.includes('"domain_modes",') && app.includes('data-testid="exception-domain-modes"'), "The policy drawer must persist and render domain modes");
for (const modeLabel of ["关闭", "影子", "可见"]) {
  assert(app.includes(`${modeLabel}`), `The rollout control must include the ${modeLabel} mode`);
}
assert(app.includes('data-testid="exception-visible-confirmation"') && app.includes("确认切换为可见"), "Visible rollout must require an explicit risk confirmation");
assert(app.includes("expected_updated_at: originalForm.updated_at"), "Policy changes must retain optimistic concurrency control");
assert(client.includes('"/api/v1/exceptions/baseline-scan"') && client.includes("expected_policy_updated_at: expectedPolicyUpdatedAt"), "Baseline requests must use the dedicated endpoint and current policy version");
assert(client.includes("export type ExceptionBaselineScanResponse") && client.includes("result: ExceptionScanResult;") && app.includes("const result = response?.result;"), "Baseline UI must consume the response wrapper and nested scan result");
assert(app.includes("result.evidence_updated") && !app.includes("result.updated}"), "Baseline results must use the backend evidence_updated metric instead of a legacy updated field");
assert(app.includes('originalForm.domain_modes[domain] !== "shadow"') && app.includes("|| hasChanges"), "Baseline execution must fail closed unless the saved mode is shadow with no unsaved changes");
assert(app.includes("基线扫描不会发送通知、不会调用 AI、不会执行修复，也不会启用任何定时任务"), "Baseline guardrails must be explicit in the policy drawer");
assert(client.includes("/api/v1/exceptions/rule-quality") && client.includes("export type ExceptionRuleQualityResponse"), "Rule-quality rollout must use the dedicated structured endpoint");
assert(app.includes('data-testid="exception-rollout-rule-quality"') && app.includes("exceptionRuleQuality({ scan_window_days: 30 }") && app.includes("row.rule_version"), "Rule-quality rollout must display scoped lifecycle and version metrics from the dedicated endpoint");
assert(app.includes("scan_job_metrics_available") && app.includes('queued_scan_jobs ?? "-"') && app.includes('failed_scan_jobs ?? "-"'), "Unavailable scan-job metrics must be shown explicitly without inventing zeroes");
assert(app.includes("不是错误率或误报率指标"), "Rule hit statistics must not be presented as an error or false-positive rate");

assert(client.includes("inFlightCrmTaskDetails") && client.includes("inFlightCrmTaskDetails.delete(taskId)"), "CRM task details must deduplicate concurrent StrictMode requests and clear settled entries");
assert(client.includes("inFlightExceptionRuleQuality") && client.includes("inFlightExceptionRuleQuality.delete(path)"), "Rule-quality requests must deduplicate concurrent StrictMode loads");
assert(app.includes("scroll-mt-20") && app.includes("items-center justify-start") && app.includes('data-testid="exception-return-context"'), "The exception return action must stay clear of the sticky top bar and account menu");
assert(app.includes("CRM_APPROVAL_ACCESS_PERMISSIONS") && app.includes('"crm_lead.approve"') && app.includes('"customer_tag.review"'), "Special approval roles must be able to enter the execution center");
assert(app.includes('sectionKey === "work" && crmApprovalIdFromPath(path)') && app.includes("directApprovalAccess"), "An exact approval deep link must defer object-level access to the backend");
assert(app.includes("function canAccessPageWithContext") && app.includes("crmApprovalIdFromPath(location)"), "Top-level routing must preserve backend-authorized approval links for applicants and current handlers without list permission");

for (const scenario of [
  "task deep link fetches the exact record and close preserves list context",
  "follow-up deep link fetches the exact record and close preserves filters",
  "approval deep link opens outside the current queue and close keeps execution view",
  "same-path popstate opens the newly requested task instead of stale drawer state",
  "source-record round trip preserves context and reopens the exact exception case",
  "approval exception renders the terminal-integrity evidence contract",
  "unsupported CRM cases explain deterministic coverage and never expose AI diagnosis or retry"
  ,"policy rollout saves shadow mode before establishing a versioned baseline"
  ,"rule quality shows versions, lifecycle counts, and unavailable scan metrics"
  ,"special approval role can open the exact approval detail"
  ,"applicant and current handler can open backend-authorized approval links without list permission"
]) {
  assert(e2e.includes(scenario), `Playwright coverage must include: ${scenario}`);
}

console.log("Exception CRM/approval stage-four assertions passed.");
