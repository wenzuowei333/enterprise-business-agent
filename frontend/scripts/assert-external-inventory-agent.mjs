import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const client = readFileSync(new URL("../src/api/client.ts", import.meta.url), "utf8");

const requiredAppTokens = [
  "应用库存异常智能体预设",
  'setName("库存异常智能体")',
  'setMinuteLimit("30")',
  'setDailyLimit("5000")',
  '"can_read_inventory_anomalies"',
  '"can_read_inventory_evidence"',
  '"can_write_inventory_diagnoses"',
  '"can_validate_inventory_actions"',
  '"can_execute_inventory_rebuild"',
  '"can_read_inventory_action_status"'
];

for (const token of requiredAppTokens) {
  if (!app.includes(token)) throw new Error(`Missing inventory agent UI contract: ${token}`);
}

if (app.includes('enabled.has("can_execute_inventory_upstream")')) {
  throw new Error("Inventory agent preset must not enable upstream execution");
}

for (const field of [
  "can_read_inventory_anomalies",
  "can_read_inventory_evidence",
  "can_execute_inventory_upstream",
  "can_read_inventory_action_status"
]) {
  if (!client.includes(`${field}: boolean`)) throw new Error(`Missing API Key payload field: ${field}`);
}

console.log("External inventory agent UI contracts verified.");
