import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const app = readFileSync(resolve("src/App.tsx"), "utf8");
const client = readFileSync(resolve("src/api/client.ts"), "utf8");

for (const snippet of [
  "can_read_sales_summary",
  "can_read_inventory_summary",
  "can_read_changes",
  "rate_limit_per_minute",
  "daily_request_limit",
  "rotateExternalApiKey",
  "externalApiKeyUsage"
]) {
  if (!client.includes(snippet)) {
    throw new Error(`Missing external API governance client contract: ${snippet}`);
  }
}

for (const snippet of [
  "每分钟请求上限",
  "每日请求上限",
  "轮换后的 API Key 仅显示一次",
  "旧 Key 将保留 15 分钟宽限期",
  "Key 调用明细",
  "row.rate_limit_per_minute"
]) {
  if (!app.includes(snippet)) {
    throw new Error(`Missing external API governance UI: ${snippet}`);
  }
}

console.log("External API governance UI contract OK");
