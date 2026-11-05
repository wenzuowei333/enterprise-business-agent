import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd());
const app = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(root, "src", "api", "client.ts"), "utf8");

function assertIncludes(source, needle, message) {
  if (!source.includes(needle)) {
    throw new Error(message);
  }
}

assertIncludes(client, "contact_name?: string | null", "关联客户行需要返回联系人字段");
assertIncludes(client, "contact_phone?: string | null", "关联客户行需要返回联系电话字段");
assertIncludes(client, "base_info_completeness?: string | null", "关联客户行需要返回资料完整度字段");

assertIncludes(app, 'headers={["客户", "客户资料", "联系方式", "负责人", "最近客户动作", "任务状态", "风险", "CRM"]}', "关联客户底盘表格需要拆分任务状态和风险列");
assertIncludes(app, "crmLinkedCustomerTaskStatusLabel(customer)", "关联客户底盘任务状态需要使用与任务明细一致的生命周期口径");
assertIncludes(app, "crmLinkedCustomerRiskLabel(customer)", "关联客户底盘风险需要单独展示，不应冒充任务状态");
assertIncludes(app, "资料不完整", "关联客户底盘统计卡需要展示资料不完整");
assertIncludes(app, "有待处理动作", "关联客户底盘统计卡需要展示有待处理动作");
assertIncludes(app, "有风险客户", "关联客户底盘统计卡需要展示有风险客户");
assertIncludes(app, 'label: "客户细节"', "关联客户底盘抽屉需要新增客户细节 tab");
assertIncludes(app, 'label: "任务明细"', "关联客户底盘和任务入口需要使用任务明细文案");
assertIncludes(app, 'title="任务明细"', "任务详情抽屉标题需要改为任务明细");
assertIncludes(app, "项目落地审批人", "任务明细抽屉需要展示项目落地审批人");
assertIncludes(app, "细节审批人", "任务明细抽屉需要展示细节审批人");
assertIncludes(app, "项目审批明细", "任务明细抽屉审批区需要展示项目审批明细");
assertIncludes(app, "CustomerQuickLinks", "关联客户列表和抽屉需要提供客户级快捷下钻链接");
assertIncludes(app, "customer_code: customerCode", "任务明细和跟进明细需要按客户编号精确过滤");
assertIncludes(app, "crmLinkedCustomerMasterTabs", "CRM 打开主数据客户档案时需要限制为动态、基础资料、经营资料、日志");
assertIncludes(app, "customerCodeFilter", "任务明细和跟进记录页面需要读取 customer_code 深链筛选");
assertIncludes(app, "清除客户筛选", "客户级深链筛选需要提供清除入口");

console.log("CRM 关联客户底盘与任务明细展示断言通过");
