import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const appSource = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");
const clientSource = fs.readFileSync(path.join(root, "src", "api", "client.ts"), "utf8");

const checks = [
  {
    ok: appSource.includes("customerProfileUpdated") && appSource.includes("setCustomerProfileUpdated"),
    message: "CrmFollowupSubmitDrawer should keep customer profile update checkbox state."
  },
  {
    ok: appSource.includes('label="完成客户基本资料更新"'),
    message: "CrmFollowupSubmitDrawer should render the 完成客户基本资料更新 checkbox."
  },
  {
    ok: appSource.includes("customer_profile_updated: customerProfileUpdated") && appSource.includes("customer_profile_approval_id: customerProfileApprovalId"),
    message: "CrmFollowupSubmitDrawer should submit customer profile update fields."
  },
  {
    ok: appSource.includes("function CrmCustomerProfileApprovalDrawer") && appSource.includes("updateCrmLinkedCustomerProfile") && !appSource.includes("createCrmCustomerProfileApprovalDraft(customerCode"),
    message: "CRM should save customer profile updates through the CRM-scoped direct update API."
  },
  {
    ok: appSource.includes('"crm_customer_profile.view"') && appSource.includes('"crm_customer_profile.submit"'),
    message: "CRM permission configuration should include customer profile view and submit permissions."
  },
  {
    ok: clientSource.includes("crmLinkedCustomerProfile") && clientSource.includes("updateCrmLinkedCustomerProfile") && clientSource.includes("/profile/update"),
    message: "API client should expose CRM-scoped customer profile read and direct update APIs."
  },
  {
    ok: clientSource.includes("customer_profile_updated: boolean;") && clientSource.includes("customer_profile_approval_id?: number | null;"),
    message: "CrmFollowupRow should expose customer profile closure fields."
  }
];

const failed = checks.filter((check) => !check.ok);
if (failed.length > 0) {
  for (const check of failed) {
    console.error(`FAIL: ${check.message}`);
  }
  process.exit(1);
}

console.log("CRM followup customer profile approval assertions passed.");
