import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const app = fs.readFileSync(path.join(frontendRoot, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(frontendRoot, "src", "api", "client.ts"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(client.includes('export type AttentionState = "normal" | "needs_attention";'), "Attention state must be typed");
assert(client.includes("attention_summary?: AttentionSummary | null;"), "Page contracts must expose attention summaries");
assert(client.includes('params.set("attention_state", options.attentionState)'), "Page requests must send the state filter");
assert(client.includes('params.set("attention_reason", options.attentionReason)'), "Page requests must send the reason filter");
assert(client.includes('params.set("snapshot_scope", options.snapshotScope)'), "Snapshot pages must send a deduplication scope");
assert(client.includes('params.set("batch_id", String(options.batchId))'), "Snapshot pages must support exact batch drilldown");

assert(app.includes("function AttentionFilterPanel"), "Pages must share one compact attention filter");
assert(app.includes('aria-pressed={active}'), "State and reason filters must expose pressed state");
assert(app.includes('onClick={() => onReasonChange(active ? "" : item.code)}'), "Clicking the active reason must clear it");
assert(app.includes("replaceCurrentQueryParams"), "Attention filters must synchronize the URL without replacing unrelated params");
assert(app.includes('snapshot_scope: batchId ? null : dateFrom || dateTo ? "daily_latest" : "latest"'), "Inventory must switch from latest to daily-latest for date ranges");
assert(app.includes('snapshot_scope: activeTab === "balance" ? batchId ? null : dateFrom || dateTo ? "daily_latest" : "latest" : null'), "Account drilldown must synchronize its effective snapshot scope");
assert(app.match(/setBatchId\(0\); setDateFrom\(value\)/g)?.length >= 2, "Changing a date must release exact-batch mode on both snapshot pages");
assert(app.includes('date_from: dateFrom,'), "Inventory must persist its date-from filter in the URL");
assert(app.includes('date_to: dateTo,'), "Inventory must persist its date-to filter in the URL");
assert(app.includes('date_from: activeTab === "balance" ? dateFrom : null'), "Account must persist its date-from filter in the URL");
assert(app.includes('date_to: activeTab === "balance" ? dateTo : null'), "Account must persist its date-to filter in the URL");
assert(app.includes('const inventoryAttentionCount = (code: string) => attentionSummary?.by_reason.find'), "Inventory metric details must use attention-summary reason counts");
assert(app.includes('detail={`锁定 ${inventoryAttentionCount("locked_stock")} / 负库存 ${inventoryAttentionCount("negative_stock")}`}'), "Inventory metric value and detail must share the attention-summary universe");

assert(app.includes('title="客户资料待补全"'), "Customer records must explain incomplete profiles");
assert(app.includes('title="库存风险"'), "Inventory must use risk terminology");
assert(app.includes("数据较旧"), "Inventory must explicitly identify stale effective data");
assert(app.includes('title="往来余额待核对"'), "Account balances must use reconciliation terminology");
assert(app.includes("不代表错账"), "Account copy must explain that non-zero balances are not errors");
assert(app.includes('<AttentionDetailNotice title="客户资料待补全"'), "Customer detail must show attention reasons");
assert(app.includes('<AttentionDetailNotice title="库存风险原因"'), "Inventory detail must show attention reasons");
assert(app.includes('<AttentionDetailNotice title="往来余额待核对原因"'), "Account detail must show attention reasons");
assert(app.includes('cell.label ?? dashboardToneLabel(cell.tone)'), "Dashboard cells must consume server labels");
assert(app.includes("cell.description"), "Dashboard cells must display server descriptions");
assert(app.includes("cell.effective_date"), "Dashboard cells must display effective dates");

console.log("Data attention filter assertions passed.");
