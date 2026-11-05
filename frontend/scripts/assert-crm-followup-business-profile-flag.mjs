import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const appSource = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");
const clientSource = fs.readFileSync(path.join(root, "src", "api", "client.ts"), "utf8");

const checks = [
  {
    ok: appSource.includes("businessProfileUpdated") && appSource.includes("setBusinessProfileUpdated"),
    message: "CrmFollowupSubmitDrawer should keep business profile update checkbox state."
  },
  {
    ok: appSource.includes('label="完成客户经营资料更新"'),
    message: "CrmFollowupSubmitDrawer should render the 完成客户经营资料更新 checkbox."
  },
  {
    ok: appSource.includes("business_profile_updated: businessProfileUpdated"),
    message: "CrmFollowupSubmitDrawer should submit business_profile_updated in the followup payload."
  },
  {
    ok: clientSource.includes("business_profile_updated: boolean;"),
    message: "CrmFollowupRow should expose business_profile_updated."
  }
];

const failed = checks.filter((check) => !check.ok);
if (failed.length > 0) {
  for (const check of failed) {
    console.error(`FAIL: ${check.message}`);
  }
  process.exit(1);
}

console.log("CRM followup business profile update flag assertions passed.");
