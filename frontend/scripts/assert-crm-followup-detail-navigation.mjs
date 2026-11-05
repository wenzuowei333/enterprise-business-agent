import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const appSource = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");

const checks = [
  {
    ok: appSource.includes("onClick={() => openFollowupDetail(followup.id)}")
      && appSource.includes("replaceCurrentQueryParams({ followup_id: followupId })"),
    message: "The follow-up list should open the detail drawer without leaving the list."
  },
  {
    ok: appSource.includes("crmFollowup(selectedFollowupId)"),
    message: "The follow-up list drawer should load the exact selected record."
  },
  {
    ok: appSource.includes("onClose={closeFollowupDetail}")
      && appSource.includes("replaceCurrentQueryParams({ followup_id: null })"),
    message: "Closing a list detail should preserve the current list page and filters."
  },
  {
    ok: appSource.includes("canOpenProject={canOpenProjects}") && appSource.includes("查看所属项目"),
    message: "Project navigation should be an explicit permission-gated action."
  },
  {
    ok: appSource.includes("crmFollowup(requestedFollowupId)"),
    message: "Project detail should load the requested follow-up independently."
  },
  {
    ok: appSource.includes("nextFollowup.project_id !== projectId"),
    message: "Project detail should reject a follow-up from another project."
  },
  {
    ok: appSource.includes("function CrmFollowupDetailDrawer"),
    message: "Project detail should provide a follow-up detail drawer."
  },
  {
    ok: ["执行动作", "客户反馈", "当前需求"].every((label) => appSource.includes(`label=\"${label}\"`)),
    message: "The drawer summary should emphasize the salesperson-entered fields."
  },
  {
    ok: appSource.includes('onClose={() => navigate("crm", `/crm/projects/${projectId}`)}'),
    message: "Legacy project deep links should still close back to their project."
  }
];

const failed = checks.filter((check) => !check.ok);
if (failed.length > 0) {
  for (const check of failed) console.error(`FAIL: ${check.message}`);
  process.exit(1);
}

console.log("CRM follow-up detail navigation assertions passed.");
