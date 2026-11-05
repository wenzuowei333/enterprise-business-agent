import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd());
const app = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(root, "src", "api", "client.ts"), "utf8");

function assertIncludes(source, needle, message) {
  if (!source.includes(needle)) throw new Error(message);
}

function assertNotIncludes(source, needle, message) {
  if (source.includes(needle)) throw new Error(message);
}

const myWorkStart = app.indexOf("function CrmMyWorkSection");
const executionStart = app.indexOf("function CrmExecutionCenterSection", myWorkStart);
const approvalStart = app.indexOf("function CrmApprovalDetailDrawer", executionStart);
if (myWorkStart < 0 || executionStart < 0 || approvalStart < 0) throw new Error("无法定位阶段 4 页面组件");

const myWork = app.slice(myWorkStart, executionStart);
const execution = app.slice(executionStart, approvalStart);

assertNotIncludes(myWork, 'label="待我审批"', "我的工作台不能继续展示重复的待我审批统计卡");
assertNotIncludes(myWork, 'label="待我支持"', "我的工作台不能继续展示重复的待我支持统计卡");
assertNotIncludes(myWork, 'title="待我审批"', "我的工作台不能继续内嵌审批队列");
assertNotIncludes(myWork, 'title="待我支持"', "我的工作台不能继续内嵌支持队列");
assertIncludes(myWork, 'label="待我补充"', "我的工作台需要保留申请人自己的待补充入口");
assertIncludes(myWork, 'label="今日任务"', "我的工作台需要聚焦当前账号今日任务");

assertIncludes(app, 'type ExecutionCenterView = "approvals" | "support"', "执行中心需要审批/支持单视图状态");
assertIncludes(execution, 'setExecutionView("approvals")', "待我审核卡需要切换到审批视图");
assertIncludes(execution, 'setExecutionView("support")', "待我支持卡需要切换到支持视图");
assertIncludes(execution, 'executionView === "approvals"', "执行中心一次只展示一个业务队列");
assertIncludes(execution, 'navigate("crm", "/crm/issues")', "支持视图需要保留完整待支持页面直达入口");

assertIncludes(client, "updateCrmLinkedCustomerBusinessProfile", "客户端需要提供经营资料直接保存接口");
assertIncludes(client, "/business-profile/update", "经营资料直接保存必须调用独立更新接口");
assertIncludes(app, "保存经营资料", "经营资料入口需要使用直接保存文案");
assertNotIncludes(app, "提交经营资料审核", "新经营资料流程不能继续要求审批");

assertIncludes(app, "function FollowupApprovalBusinessSummary", "跟进审批详情需要独立业务摘要组件");
assertIncludes(app, 'label="客户反馈"', "跟进审批摘要需要展示客户反馈");
assertIncludes(app, 'label="当前需求"', "跟进审批摘要需要展示当前需求");
assertIncludes(app, 'label="下一步动作"', "跟进审批摘要需要展示下一步动作");

console.log("CRM 我的工作与执行中心阶段 4 断言通过");
