import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd());
const app = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");

function assertIncludes(source, needle, message) {
  if (!source.includes(needle)) throw new Error(message);
}

const drawerStart = app.indexOf("function CrmApprovalDetailDrawer");
const drawerEnd = app.indexOf("function CrmDelayApprovalDrawer", drawerStart);
if (drawerStart < 0 || drawerEnd < 0) throw new Error("无法定位审批详情抽屉");
const drawer = app.slice(drawerStart, drawerEnd);
const followupCardsStart = app.indexOf("function FollowupBusinessSummaryCards");
const followupCardsEnd = app.indexOf("function FollowupApprovalBusinessSummary", followupCardsStart);
if (followupCardsStart < 0 || followupCardsEnd < 0) throw new Error("无法定位跟进审批业务卡片");
const followupCards = app.slice(followupCardsStart, followupCardsEnd);

assertIncludes(app, "function ApprovalBusinessHeader", "审批详情需要统一业务概览头部");
assertIncludes(app, "function ProjectApplicationApprovalSummary", "项目立项审批需要专属业务内容组件");
assertIncludes(app, "function FollowupApprovalBusinessSummary", "跟进审批需要专属业务内容组件");
assertIncludes(followupCards, 'label="是否需要支持" value={followupFlagLabel(supportRequested)}', "跟进审批需要显示一线提交的支持状态");
assertIncludes(followupCards, 'label="本任务是否闭环" value={followupFlagLabel(Boolean(followup.is_closed))}', "跟进审批需要显示一线提交的闭环状态");
const followupScheduleOrder = ["下次跟进", "支持类型", "是否需要支持", "本任务是否闭环"].map((label) => followupCards.indexOf(`label="${label}"`));
if (followupScheduleOrder.some((index) => index < 0) || followupScheduleOrder.some((index, position) => position > 0 && index <= followupScheduleOrder[position - 1])) {
  throw new Error("跟进审批推进安排字段顺序不正确");
}
assertIncludes(app, 'title="项目与人员"', "项目审批需要展示项目和流程人员");
assertIncludes(app, 'title="客户任务分配"', "项目审批需要展示客户任务分配明细");
assertIncludes(drawer, "高级补充数据（一般无需修改）", "补充审批时原始载荷只能放在折叠高级区域");
assertIncludes(drawer, "operator_user_label", "审批时间线需要优先显示操作人名称");
assertIncludes(drawer, "created_by_user_label", "附件需要优先显示上传人名称");
assertIncludes(app, '<details className="rounded-lg border border-slate-200 bg-white p-4">', "系统原始载荷必须默认折叠");

console.log("CRM 审批详情阶段 6 断言通过");
