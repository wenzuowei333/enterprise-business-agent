import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd());
const app = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(root, "src", "api", "client.ts"), "utf8");

function assertIncludes(source, needle, message) {
  if (!source.includes(needle)) throw new Error(message);
}

assertIncludes(app, "applyCustomerMetricFilter", "关联客户统计卡需要驱动列表筛选");
assertIncludes(app, 'applyCustomerMetricFilter("profile_incomplete")', "资料不完整统计卡需要筛选缺资料客户");
assertIncludes(app, 'applyCustomerMetricFilter("pending_action")', "待处理动作统计卡需要筛选待处理客户");
assertIncludes(app, 'applyCustomerMetricFilter("risk")', "风险客户统计卡需要筛选风险客户");
assertIncludes(app, "applyFollowupMetricFilter", "跟进记录统计卡需要驱动列表筛选");
assertIncludes(app, 'review_scope: reviewScope', "待审核/补充统计卡需要使用联合审核范围");
assertIncludes(client, "customer_name?: string | null", "跟进记录响应需要提供客户名称");
assertIncludes(app, "followup.customer_name", "跟进记录客户列需要优先展示客户名称");
assertIncludes(app, "onEditBusinessProfile", "关联客户档案需要提供经营资料更新快捷动作");
assertIncludes(app, ">经营资料更新</Button>", "经营资料更新需要使用独立醒目按钮");
assertIncludes(app, 'sidebar={null}', "关联客户详情需要移除重复的右侧摘要栏");

console.log("CRM 客户全景阶段 2 断言通过");
