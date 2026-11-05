import fs from "node:fs";

const source = fs.readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

assert(
  source.includes('type CrmCustomerContextTab = "profile" | "businessProfile"'),
  "关联客户抽屉的页签类型必须包含独立经营资料页签。"
);
assert(
  source.includes('key: "businessProfile"') && source.includes('label: "经营资料"'),
  "关联客户抽屉必须展示经营资料页签。"
);
assert(
  source.includes('hasPermission(permissions, "crm_business_profile.view")'),
  "关联客户经营资料查看必须使用 CRM 作用域权限 crm_business_profile.view。"
);
assert(
  source.includes('hasPermission(permissions, "crm_business_profile.submit")'),
  "关联客户经营资料提交必须使用 CRM 作用域权限 crm_business_profile.submit。"
);
assert(
  source.includes("crmLinkedCustomerBusinessProfile(customerCode)"),
  "关联客户经营资料页签必须读取 CRM 作用域经营资料接口。"
);
assert(
  source.includes("<CustomerBusinessProfilePanel") && source.includes("<CrmBusinessProfileApprovalDrawer"),
  "关联客户经营资料页签必须复用完整经营资料展示和编辑抽屉。"
);
assert(
  source.includes("updateCrmLinkedCustomerBusinessProfile(customerCode, payload)"),
  "关联客户经营资料必须通过 CRM 作用域接口直接保存。"
);
assert(
  source.includes("保存后立即同步主数据"),
  "关联客户经营资料保存后必须明确提示立即同步主数据。"
);

console.log("CRM 关联客户经营资料页签检查通过");
