import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd());
const app = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");

function assertIncludes(source, needle, message) {
  if (!source.includes(needle)) throw new Error(message);
}

function assertNotIncludes(source, needle, message) {
  if (source.includes(needle)) throw new Error(message);
}

const businessStart = app.indexOf('key: "business-execution"');
const businessEnd = app.indexOf('key: "my-work"', businessStart);
if (businessStart < 0 || businessEnd < 0) throw new Error("无法定位业务执行菜单配置");
const businessExecution = app.slice(businessStart, businessEnd);

assertIncludes(
  businessExecution,
  'key: "task-details", label: "任务明细", desc: "查看任务、项目上下文并填写跟进反馈", icon: ClipboardList, sectionKey: "tasks", path: "/crm/tasks", permissions: ["crm_task.view"]',
  "业务执行中的任务明细必须统一进入 /crm/tasks，并只以任务查看权限控制入口"
);
assertNotIncludes(businessExecution, 'path: "/crm/followup-entry"', "业务执行不能继续进入重复的旧任务队列");
assertIncludes(app, '"/crm/followup-entry": "/crm/tasks"', "旧任务队列地址必须兼容跳转到正式任务明细页");

assertIncludes(app, "function applyTaskMetricFilter", "任务明细页需要提供统一的统计卡筛选函数");
assertIncludes(app, 'applyTaskMetricFilter("open")', "未闭环统计卡需要筛选未闭环任务");
assertIncludes(app, 'applyTaskMetricFilter("support")', "待支持统计卡需要筛选待支持任务");
assertIncludes(app, 'applyTaskMetricFilter("closed")', "已闭环统计卡需要筛选已闭环任务");
assertIncludes(app, 'active={scopeFilter === "open"}', "任务统计卡需要显示当前生效的筛选状态");

assertIncludes(
  app,
  'navigate("crm", withQuery("/crm/tasks", { project_id: project.id }))',
  "项目列表必须提供按项目过滤的任务明细直达入口"
);
assertIncludes(app, '>任务明细</button>', "项目列表中的任务直达入口需要使用明确业务文案");
assertIncludes(app, 'Table headers={["项目", "类型", "状态", "细节审批人", "一线业务员", "项目进度", "风险", "审批", "最近跟进", "更新时间", "操作"]}', "项目列表需要增加独立操作列");

console.log("CRM 业务执行阶段 3 断言通过");
