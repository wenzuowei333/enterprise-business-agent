import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(frontendRoot, "..");
const app = fs.readFileSync(path.join(frontendRoot, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(frontendRoot, "src", "api", "client.ts"), "utf8");
const schema = fs.readFileSync(path.join(repositoryRoot, "backend", "app", "schemas", "crm.py"), "utf8");
const routes = fs.readFileSync(path.join(repositoryRoot, "backend", "app", "api", "routes", "crm_projects.py"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const tableStart = app.indexOf('Table headers={["客户", "任务明细", "项目"');
const tableEnd = app.indexOf("</Table>", tableStart);
assert(tableStart >= 0 && tableEnd > tableStart, "无法定位任务明细列表表格");
const taskTable = app.slice(tableStart, tableEnd);

assert(taskTable.includes("本次项目的目的：{crmProjectPurposeText(task.project_purpose)}"), "任务明细列表需要显示项目申请目的");
assert(!taskTable.includes("问题：{displayValue(task.business_issue_point)}"), "任务明细列表不能继续显示问题行");
assert(!taskTable.includes("目标：{displayValue(task.round_target)}"), "任务明细列表不能继续显示目标行");
assert(app.includes('label="本次项目的目的" value={crmProjectPurposeText(project.purpose)}'), "任务详情需要使用统一项目目的标签");
assert(client.includes("project_purpose?: string | null;"), "Web 任务类型需要暴露 project_purpose");
assert(schema.includes("project_purpose: str | None = None"), "后端任务响应需要暴露可选 project_purpose");
assert(routes.includes("def _fill_task_project_purpose"), "后端需要批量填充当前页项目目的");
assert(routes.includes("CrmProject.purpose.ilike(like)"), "任务搜索需要支持项目目的");

console.log("CRM task project purpose assertions passed.");
