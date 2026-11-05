import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const appSource = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");
const clientSource = fs.readFileSync(path.join(root, "src", "api", "client.ts"), "utf8");

const checks = [
  [appSource.includes("function CustomerTagSelector"), "Customer edit form must use the shared tag selector."],
  [appSource.includes("新增并选中"), "Tag selector must support inline creation."],
  [appSource.includes("共享标签库"), "Tag selector must expose shared tag management."],
  [appSource.includes("CustomerTagFilterControl"), "Customer list must use a multi-select tag filter."],
  [clientSource.includes('customerTagMatch?: "any" | "all"'), "Customer list API must expose match semantics."],
  [clientSource.includes('params.set("customer_tag_match", options.customerTagMatch)'), "Web must send tag match semantics."],
  [clientSource.includes("updateExternalApiKeyCustomerFields"), "API Key customer field permissions must be editable."],
  [appSource.includes('field === "customer_tags"'), "API Key field editor must expose customer tags."],
];

const failed = checks.filter(([ok]) => !ok);
if (failed.length > 0) {
  for (const [, message] of failed) console.error(`FAIL: ${message}`);
  process.exit(1);
}

console.log("Customer tag catalog assertions passed.");
