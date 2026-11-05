import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(frontendRoot, "..");
const app = fs.readFileSync(path.join(frontendRoot, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(frontendRoot, "src", "api", "client.ts"), "utf8");
const routes = fs.readFileSync(path.join(repositoryRoot, "backend", "app", "api", "routes", "approvals.py"), "utf8");
const projectService = fs.readFileSync(path.join(repositoryRoot, "backend", "app", "services", "crm_project_service.py"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(client.includes("approvedProjectWithdrawalPreview"), "Web API must expose the withdrawal preview request");
assert(client.includes("withdrawApprovedProject"), "Web API must expose the approved-project withdrawal action");
assert(app.includes('data-testid="project-approval-withdrawal-dialog"'), "Approval detail must use a dedicated withdrawal dialog");
assert(app.includes("撤回原因（必填，5–1000 字）"), "Withdrawal dialog must require a bounded reason");
assert(app.includes('data-testid="project-frozen-banner"'), "Project detail must display the frozen banner");
assert(app.includes('data-testid="task-project-frozen-banner"'), "Task detail must display the frozen banner");
assert(app.includes('data-testid="work-item-project-frozen-banner"'), "Work item detail must display the frozen banner");
assert(app.includes('withdraw_approved_project: "审批人撤回已通过审核"'), "Timeline must distinguish approver withdrawal from applicant cancellation");
assert(routes.includes('@router.get("/{approval_id}/withdrawal-preview"'), "Backend must expose withdrawal preview");
assert(routes.includes('@router.post("/{approval_id}/withdraw-approved"'), "Backend must expose withdrawal action");
assert(projectService.includes('"error_code": "PROJECT_FROZEN"'), "Backend project write guard must return PROJECT_FROZEN");

console.log("Approved project withdrawal assertions passed.");
