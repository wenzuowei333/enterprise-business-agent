import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const appSource = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");
const clientSource = fs.readFileSync(
  path.join(root, "src", "api", "client.ts"),
  "utf8",
);
const workspaceSource = fs.readFileSync(
  path.join(root, "src", "components", "customer-operations.tsx"),
  "utf8",
);
const externalApiSource = fs.readFileSync(
  path.join(
    root,
    "..",
    "backend",
    "app",
    "api",
    "routes",
    "external_api_v2_operations.py",
  ),
  "utf8",
);

const checks = [
  [
    appSource.includes('path: "/crm/customer-tags"'),
    "CRM navigation must expose structured customer tags.",
  ],
  [
    appSource.includes('{ key: "tags" as const, label: "标签管理" }'),
    "Customer detail must expose the tag-management tab.",
  ],
  [
    appSource.includes("initialCustomer={{ customer_code: customerCode, customer_name: customerName }}"),
    "Customer detail tag management must preserve the current customer context.",
  ],
  [
    workspaceSource.includes("initialCustomer?:") && workspaceSource.includes("embedded?: boolean"),
    "Customer tag workspace must support embedded customer-detail mode.",
  ],
  [
    appSource.includes('path: "/crm/sales-orders"'),
    "CRM navigation must expose sales orders.",
  ],
  [
    appSource.includes('path: "/crm/deliveries"'),
    "CRM navigation must expose delivery execution.",
  ],
  [
    workspaceSource.includes('label: "客户分类"'),
    "Customer classification category is missing.",
  ],
  [
    workspaceSource.includes('label: "产品机会"'),
    "Product opportunity category is missing.",
  ],
  [
    workspaceSource.includes('label: "采购特征"'),
    "Purchase characteristic category is missing.",
  ],
  [
    workspaceSource.includes('label: "配送需求"'),
    "Delivery requirement category is missing.",
  ],
  [
    workspaceSource.includes("客户筛选"),
    "Structured customer filtering view is missing.",
  ],
  [
    workspaceSource.includes("结构化复核"),
    "Legacy mapping must require structured review.",
  ],
  [
    workspaceSource.includes('"need_supplement"'),
    "Item-level supplement review is missing.",
  ],
  [
    workspaceSource.includes("temporaryRequirements"),
    "Order-specific temporary delivery requirements are missing.",
  ],
  [
    workspaceSource.includes("配送要求快照"),
    "Immutable delivery requirement snapshot UI is missing.",
  ],
  [
    workspaceSource.includes("重新同步要求"),
    "Explicit pre-dispatch requirement refresh is missing.",
  ],
  [
    workspaceSource.includes("订单 Excel 导入"),
    "Sales-order Excel import UI is missing.",
  ],
  [
    workspaceSource.includes("取消订单"),
    "Pre-dispatch order cancellation UI is missing.",
  ],
  [workspaceSource.includes("交付附件"), "Delivery attachment UI is missing."],
  [
    workspaceSource.includes("变更历史"),
    "Customer-tag history timeline is missing.",
  ],
  [
    workspaceSource.includes("目录版本维护"),
    "Formal catalog version management is missing.",
  ],
  [
    workspaceSource.includes("产品品类 *"),
    "Product opportunity structured fields are missing.",
  ],
  [
    workspaceSource.includes("平均采购间隔（天）*"),
    "Purchase characteristic statistics are missing.",
  ],
  [
    workspaceSource.includes("订单确认时自动带入"),
    "Delivery requirement structured fields are missing.",
  ],
  [
    workspaceSource.includes("采购特征推荐"),
    "Purchase recommendation workflow is missing.",
  ],
  [
    clientSource.includes("/api/v1/customer-tagging/customers?${params}"),
    "Structured customer filter API is missing.",
  ],
  [
    clientSource.includes("/refresh-requirements"),
    "Requirement refresh API is missing.",
  ],
  [
    clientSource.includes("/api/v1/fulfillment/orders/import"),
    "Order import client API is missing.",
  ],
  [
    clientSource.includes("/attachments/${attachmentId}/download"),
    "Delivery attachment download API is missing.",
  ],
  [
    clientSource.includes("/catalog/versions/${versionId}/activate"),
    "Catalog activation API is missing.",
  ],
  [
    externalApiSource.includes('if "customer_tag_profile" in fields:'),
    "External structured customer-tag field is missing.",
  ],
];

const failed = checks.filter(([ok]) => !ok);
if (failed.length > 0) {
  for (const [, message] of failed) console.error(`FAIL: ${message}`);
  process.exit(1);
}

console.log("Structured customer tags and fulfillment assertions passed.");
