import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const app = readFileSync(resolve("src/App.tsx"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const crmSectionsStart = app.indexOf("const crmSections");
const crmSectionsEnd = app.indexOf("const crmNavGroups", crmSectionsStart);
const crmSections = app.slice(crmSectionsStart, crmSectionsEnd);

assert(app.includes('| "external-api"'), "账号管理缺少 external-api Tab 类型");
assert(app.includes('{ tab: "external-api", label: "外部 API", permissions: ["external_api_key.view", "external_api_key.create", "external_api_key.revoke"] }'), "外部 API Tab 权限配置不完整");
assert(app.includes('if (path.startsWith("/users/external-api")) return "external-api";'), "缺少账号管理外部 API 路由解析");
assert(app.includes('"/crm/api-access": "/users/external-api"'), "旧 CRM 接口开放地址没有兼容跳转");
assert(app.includes("function ExternalApiManagementPanel"), "外部 API 管理内容未迁入账号管理");
assert(app.includes('activeAccountTab === "external-api"'), "账号管理没有渲染外部 API 内容");
assert(app.includes('path: "/users/external-api"'), "全局入口没有指向账号管理外部 API 路由");
assert(app.includes('resources: ["external_api_key"]'), "账号管理权限分组缺少 external_api_key");
assert(!crmSections.includes('key: "api-access"'), "CRM 仍保留接口开放正式入口");
assert(!app.includes("function CrmApiAccessSection"), "CRM 专属 API 管理组件仍然存在");
assert(!app.includes('target: { page: "crm", path: "/crm/api-access" }'), "仍有快捷入口指向 CRM 旧路由");
assert(!app.includes('external_api.view') && !app.includes('external_api.manage'), "前端仍使用失效的外部 API 权限别名");

console.log("外部 API 已完整归入账号管理");
