import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const app = fs.readFileSync(path.join(frontendRoot, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(frontendRoot, "src", "api", "client.ts"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(client.includes("latest_return_feedback?: {"), "Approval rows must expose structured return feedback");
assert(client.includes('event_type: "supplement_request" | "reject";'), "Return feedback must distinguish supplement and rejection events");
assert(app.includes("function ApprovalReturnFeedbackPanel"), "Approval details must render a prominent return feedback panel");
assert(app.includes("未填写具体原因，请联系审批人"), "Historical empty feedback must have a clear fallback");
assert(app.includes("showReturnFeedback"), "My submissions must opt into the return reason preview");
assert(app.includes("<ApprovalReturnFeedbackPanel approval={currentApproval} />"), "Submission editor and approval detail must share the feedback panel");
assert(app.match(/<ApprovalReturnFeedbackPanel approval=\{currentApproval\} \/>/g)?.length === 2, "Both submission editor and approval detail must show feedback");
assert(app.includes("请填写需要申请人补充的具体内容。"), "General approval supplement requests must require a reason");
assert(app.includes("请填写需要一线补充的具体内容。"), "Followup review supplement requests must require a reason");
assert(app.match(/请填写具体驳回原因。/g)?.length === 2, "Both Web approval flows must require a rejection reason");
assert(!app.includes('cleanNullable(comment) || "请补充审批材料"'), "General approvals must not silently create a generic supplement reason");
assert(!app.includes('cleanNullable(reviewNote) || "跟进记录未通过审核"'), "Followup reviews must not silently create a generic rejection reason");

console.log("Approval return feedback assertions passed.");
