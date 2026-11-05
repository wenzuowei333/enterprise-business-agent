import fs from "node:fs";

const source = fs.readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function extractBalancedBlock(text, startIndex, openChar, closeChar) {
  let depth = 0;
  let quote = null;
  let escaped = false;
  let started = false;

  for (let index = startIndex; index < text.length; index += 1) {
    const char = text[index];
    if (quote) {
      if (escaped) {
        escaped = false;
        continue;
      }
      if (char === "\\") {
        escaped = true;
        continue;
      }
      if (char === quote) {
        quote = null;
      }
      continue;
    }
    if (char === "\"" || char === "'" || char === "`") {
      quote = char;
      continue;
    }
    if (char === openChar) {
      depth += 1;
      started = true;
    }
    if (char === closeChar) {
      depth -= 1;
      if (started && depth === 0) {
        return text.slice(startIndex, index + 1);
      }
    }
  }
  throw new Error(`无法提取 ${openChar}${closeChar} 平衡代码块`);
}

function extractConstArray(name) {
  const constIndex = source.indexOf(`const ${name}`);
  assert(constIndex >= 0, `未找到 ${name} 配置`);
  const assignmentIndex = source.indexOf("=", constIndex);
  assert(assignmentIndex >= 0, `${name} 缺少赋值表达式`);
  const arrayIndex = source.indexOf("[", assignmentIndex);
  assert(arrayIndex >= 0, `${name} 不是数组配置`);
  return extractBalancedBlock(source, arrayIndex, "[", "]");
}

function extractObjectByKey(block, key) {
  const keyIndex = block.indexOf(`key: "${key}"`);
  assert(keyIndex >= 0, `未找到菜单分组 ${key}`);
  const objectStart = block.lastIndexOf("{", keyIndex);
  assert(objectStart >= 0, `菜单分组 ${key} 缺少对象起点`);
  return extractBalancedBlock(block, objectStart, "{", "}");
}

function labelsOf(objectBlock) {
  return [...objectBlock.matchAll(/label: "([^"]+)"/g)].map((match) => match[1]);
}

function assertEntryLabels(groupBlock, expected) {
  const labels = labelsOf(groupBlock).slice(1);
  assert(
    JSON.stringify(labels) === JSON.stringify(expected),
    `菜单项顺序不符合预期。\n实际: ${labels.join(" / ")}\n预期: ${expected.join(" / ")}`
  );
}

const crmNavGroups = extractConstArray("crmNavGroups");
assert(!crmNavGroups.includes('key: "customer-view"'), "客户视图不能继续作为 CRM 菜单入口");
assert(!crmNavGroups.includes('label: "客户视图"'), "客户视图不能继续显示在 CRM 菜单中");
assert(!crmNavGroups.includes('label: "客户主档"'), "客户主档不能继续显示在 CRM 菜单中");
assert(crmNavGroups.includes('label: "关联客户底盘"'), "CRM 应保留关联客户底盘入口");
assert(crmNavGroups.includes('path: "/crm/customers"'), "关联客户底盘必须进入 CRM 客户上下文页");

const customerOverview = extractObjectByKey(crmNavGroups, "customer-overview");
assert(labelsOf(customerOverview)[0] === "用来看：客户全景", "客户全景分组标题不正确");
assertEntryLabels(customerOverview, ["关联客户底盘", "客户标签", "跟进记录", "数据中心", "客户开发"]);
assert(customerOverview.includes('key: "lead-development"'), "客户全景必须提供客户开发入口");
assert(customerOverview.includes('path: "/crm/leads"'), "客户开发入口必须进入 /crm/leads");
assert(customerOverview.includes('permissions: ["crm_lead.view"]'), "客户开发入口必须按 crm_lead.view 权限显示");
assert(!customerOverview.includes('key: "task-ledger"'), "任务明细应归入业务执行，不能继续出现在客户全景");
assert(!customerOverview.includes('key: "project-ledger"'), "项目列表应归入业务执行，不能继续出现在客户全景");
assert(!customerOverview.includes('key: "review-records"'), "复盘管理不能继续作为客户全景独立入口");
assert(!customerOverview.includes('key: "business-insights"'), "经营分析不能继续作为独立 CRM 菜单入口");
assert(!customerOverview.includes('path: "/crm/insights"'), "经营分析旧路径不能继续挂在 CRM 菜单中");
assert(source.includes('"/crm/projects?view=analysis"'), "项目列表必须保留经营分析 Tab 的直接访问路径");
assert(source.includes('label="经营分析"') || source.includes('经营分析'), "项目列表合并页必须保留经营分析页签");

const businessExecution = extractObjectByKey(crmNavGroups, "business-execution");
assert(labelsOf(businessExecution)[0] === "用来干具体的事：业务执行", "业务执行分组标题不正确");
assertEntryLabels(businessExecution, ["项目申请", "项目列表", "任务明细", "销售订单", "配送执行", "待支持填写"]);
assert(!businessExecution.includes('label: "客户推进"'), "业务执行不应保留和客户任务/跟进重复的客户推进入口");
assert(businessExecution.includes('path: "/crm/projects"'), "项目列表必须进入项目列表页");
assert(businessExecution.includes('sectionKey: "tasks", path: "/crm/tasks"'), "任务明细必须进入统一任务明细页");
assert(!businessExecution.includes('path: "/crm/followup-entry"'), "业务执行不能继续进入重复的旧任务队列");
assert(!businessExecution.includes('path: "/crm/business-profile-submit"'), "经营资料不能继续作为业务执行独立入口");
assert(!businessExecution.includes('path: "/crm/customer-profile-submit"'), "基本资料不能继续作为业务执行独立入口");
assert(!businessExecution.includes('path: "/crm/tasks?mode=followup"'), "跟进记录填写不能继续复用客户任务页伪入口");

const myWork = extractObjectByKey(crmNavGroups, "my-work");
assert(labelsOf(myWork)[0] === "看清楚我该干什么：我的工作", "我的工作分组标题不正确");
assertEntryLabels(myWork, ["今日待办", "待我补充", "执行中心", "我的提交"]);
assert(!myWork.includes('key: "overdue-alerts"'), "超期提醒应由执行中心承接，不能继续作为我的工作独立入口");
assert(!myWork.includes('key: "need-review"'), "待我审核应由执行中心承接，不能继续作为我的工作独立入口");
assert(!myWork.includes('key: "need-support"'), "待我支持应由执行中心承接，不能继续作为我的工作独立入口");

assert(source.includes('const CRM_LEGACY_PATH_REDIRECTS'), "缺少 CRM 旧地址兼容映射");
assert(source.includes('"/crm/business-profile-submit": "/crm/customers"'), "经营资料旧入口必须兼容跳转到关联客户底盘");
assert(source.includes('"/crm/customer-profile-submit": "/crm/customers"'), "基本资料旧入口必须兼容跳转到关联客户底盘");
assert(source.includes('"/crm/followup-entry": "/crm/tasks"'), "旧任务队列必须兼容跳转到统一任务明细页");
assert(source.includes('"/crm/insights": "/crm/projects?view=analysis"'), "经营分析旧入口必须兼容跳转到项目列表分析页");
assert(source.includes('"/crm/reviews": "/crm/projects"'), "复盘管理旧入口必须兼容跳转到项目列表");
assert(source.includes('"/crm/assistant": "/exceptions?assistant=open"'), "CRM AI 旧入口必须兼容打开异常中心 AI 助手");
assert(source.includes("function canonicalCrmPath"), "缺少 CRM 旧地址标准化函数");
assert(source.includes("window.history.replaceState(null, \"\", canonicalPath)"), "进入旧 CRM 地址时必须替换为新的标准地址");
assert(
  (source.match(/onFocus=\{\(\) => setActiveMenuGroupKey\(group\.key\)\}/g) ?? []).length === 1,
  "CRM 顶部分组按钮不能同时用获取焦点和点击切换菜单，否则配送执行等深层入口会立即关闭"
);

const sections = extractConstArray("crmSections");
assert(sections.includes('key: "projects", label: "项目列表"'), "项目页面术语必须统一为项目列表");
assert(sections.includes('key: "tasks", label: "任务明细"'), "任务查看和填写入口必须统一为任务明细");
assert(sections.includes('key: "submissions", label: "我的提交"'), "个人提交记录必须统一为我的提交");

const crmHomeFunctionIndex = source.indexOf("function CrmHomeSection");
assert(crmHomeFunctionIndex >= 0, "缺少 CRM 默认首页组件");
const crmHomeBodyStart = source.indexOf("{", source.indexOf("}) {", crmHomeFunctionIndex));
const crmHomeBody = extractBalancedBlock(source, crmHomeBodyStart, "{", "}");
assert(crmHomeBody.includes("<CrmStandardHomeSection"), "CRM 默认首页必须使用业务工作台");
assert(!crmHomeBody.includes("<CrmAiHomeSection"), "管理员不能被自动分流到 AI 首页");
assert(!sections.includes('key: "assistant"'), "CRM 页面配置不能残留 AI 助手正式入口");
assert(!source.includes('activeSectionKey === "assistant"'), "CRM 页面渲染不能残留 AI 助手分支");
assert(!crmNavGroups.includes('/crm/assistant'), "CRM 导航不能残留 AI 助手地址");

assert(source.includes("function buildCrmCustomerPath"), "缺少 CRM 客户视图统一路径构建函数");
assert(source.includes('return withQuery("/crm/customers", { q: query, open });'), "CRM 客户路径必须同时携带 q 与 open 参数");
assert(source.includes("openCrmCustomer: (target: MasterRecordJump) => void;"), "统一跳转工具缺少 openCrmCustomer 能力");
assert(source.includes("jumpTools.openCrmCustomer({ code: customerCode, name: customerName })"), "客户资料关联动作必须能反向打开 CRM 客户视图");
assert(source.includes('const masterLookup = code || name;') && source.includes('kind: "customers",') && source.includes('q: masterLookup,') && source.includes('open: masterLookup,'), "CRM 客户抽屉返回主数据时必须自动打开对应客户详情");
assert(source.includes('type CrmCustomerContextTab = "profile" | "businessProfile" | "details" | "overview"'), "关联客户抽屉必须把客户档案、经营资料和客户细节作为一级页签");
assert(source.includes('useState<CrmCustomerContextTab>("profile")'), "点击关联客户后默认应打开客户档案页签");
assert(source.includes('{ key: "profile", label: "客户档案"'), "关联客户抽屉缺少客户档案页签");
assert(source.includes('key: "businessProfile"') && source.includes('label: "经营资料"'), "关联客户抽屉缺少经营资料页签");
assert(source.includes("function CrmCustomerProfilePanel"), "关联客户抽屉缺少 CRM 项目期客户档案展示组件");

console.log("CRM 菜单结构检查通过");
