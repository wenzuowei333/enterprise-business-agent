import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(frontendRoot, "..");
const app = fs.readFileSync(path.join(frontendRoot, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(frontendRoot, "src", "api", "client.ts"), "utf8");
const schema = fs.readFileSync(path.join(repositoryRoot, "backend", "app", "schemas", "crm.py"), "utf8");
const routes = fs.readFileSync(path.join(repositoryRoot, "backend", "app", "api", "routes", "crm_projects.py"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(/followup_submission_state\?:\s*\|?\s*"unsubmitted"\s*\|\s*"submitted"\s*\|\s*"needs_action"\s*\|\s*null;/.test(client), "Web task type must expose the submission state");
assert(client.includes("latest_followup_approval_status?: string | null;"), "Web task type must expose the latest approval status");
assert(client.includes("latest_followup_submitted_at?: string | null;"), "Web task type must expose the latest submission time");
assert(client.includes("submission_summary: {"), "Task pages must expose server-side submission counts");

assert(schema.includes('CrmFollowupSubmissionState = Literal["unsubmitted", "submitted", "needs_action"]'), "Backend schema must constrain submission states");
assert(schema.includes("class CrmTaskSubmissionSummary(BaseModel):"), "Backend task page must expose a submission summary");
assert(schema.includes("submission_summary: CrmTaskSubmissionSummary"), "Task page contract must include the summary");

assert(routes.includes("def _latest_followup_submission_subquery"), "Backend must derive the latest submission in one query");
assert(routes.includes("func.row_number()"), "Latest submission must be selected per task without N+1 queries");
assert(routes.includes("def _task_submission_page_query"), "Backend must share summary and filtering logic");
assert(routes.includes("def _fill_task_followup_submission"), "Backend must bulk-fill task submission fields");
assert(routes.match(/followup_submission_state: Literal\["unsubmitted", "submitted", "needs_action"\] \| None = None/g)?.length === 2, "Both task page endpoints must accept the submission filter");

assert(app.includes('initialQueryParam("followup_submission_state")'), "Task page must read deep-linked submission filters");
assert(app.includes("followup_submission_state: followupSubmissionState || undefined"), "Task page must send the selected state to the server");
assert(app.includes("按当前任务筛选范围统计，不受分页影响。"), "Submission summary must explain its full-range count");
assert(app.includes('aria-label="跟进提交状态"'), "Task page must expose an accessible submission segment control");
assert(app.includes('label="提交状态"'), "Task toolbar must include a submission filter");
assert(app.includes('Table headers={["客户", "任务明细", "项目", "执行人", "状态", "跟进提交"'), "Task table must include the submission column");
assert(app.includes("<CrmTaskSubmissionCell task={task} />"), "Each task row must render its submission state");
assert(app.includes("colSpan={10}"), "Task empty state must span the new column count");
assert(app.includes('setFollowupSubmissionState("")'), "Reset must restore the all-submissions view");

console.log("CRM task submission status assertions passed.");
