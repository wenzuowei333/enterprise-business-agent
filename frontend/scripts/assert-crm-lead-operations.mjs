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

assertIncludes(app, 'type CrmLeadWorkspaceView = "mine" | "public-pool" | "sla" | "campaigns" | "analysis"', "客户开发应包含我的线索、公海、SLA、活动和分析视图");
assertIncludes(app, 'label: "我的线索"', "客户开发应提供我的线索入口");
assertIncludes(app, 'label: "公海线索"', "客户开发应提供公海线索入口");
assertIncludes(app, 'label: "SLA 异常"', "客户开发应提供 SLA 异常入口");
assertIncludes(app, 'label: "活动管理"', "客户开发应提供活动管理入口");
assertIncludes(app, 'label: "团队分析"', "客户开发应提供团队分析入口");
assertIncludes(app, 'hasPermission(permissions, "crm_lead.claim")', "公海认领必须检查认领权限");
assertIncludes(app, 'hasPermission(permissions, "crm_lead.recycle")', "回收线索必须检查回收权限");
assertIncludes(app, 'hasPermission(permissions, "crm_lead.analytics")', "团队分析必须检查分析权限");
assertIncludes(app, 'hasPermission(permissions, "crm_lead_campaign.manage")', "活动管理必须检查管理权限");
assertIncludes(app, '<CrmLeadPublicPoolPanel', "公海线索必须使用独立展示组件");
assertIncludes(app, '<CrmLeadSlaPanel', "SLA 异常必须使用独立展示组件");
assertIncludes(app, '<CrmLeadCampaignPanel', "活动管理必须使用独立展示组件");
assertIncludes(app, '项目预填', "转正详情必须继续展示项目预填");
assertIncludes(app, '归因来源', "转正详情必须展示来源与活动归因");

assertIncludes(client, 'export type CrmLeadPoolRow', "客户端必须定义公海线索安全合同");
assertIncludes(client, 'export function crmLeadPublicPoolPage', "客户端必须提供公海分页请求");
assertIncludes(client, 'export function claimCrmLead', "客户端必须提供认领请求");
assertIncludes(client, 'export function recycleCrmLead', "客户端必须提供回收请求");
assertIncludes(client, 'export function crmLeadCampaignsPage', "客户端必须提供活动分页请求");
assertIncludes(client, 'export function updateCrmLeadOperationPolicy', "客户端必须提供 SLA 策略更新请求");
assertIncludes(client, 'export type CrmLeadOperationsAnalytics', "客户端必须定义运营分析合同");
const poolType = client.slice(client.indexOf("export type CrmLeadPoolRow"), client.indexOf("export type CrmLeadCampaignRow"));
assertNotIncludes(poolType, "contact_name", "公海线索合同不得暴露联系人");
assertNotIncludes(poolType, "contact_phone", "公海线索合同不得暴露联系电话");

console.log("CRM 客户开发运营工作台断言通过");
