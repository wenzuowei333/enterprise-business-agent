import fs from "node:fs";

const source = fs.readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(source.includes("function CrmDataCenterScopeButton"), "CRM 数据中心统计卡必须改为低噪声筛选按钮组件");
assert(!source.includes("<CrmDataCenterDimensionPanel dimensions="), "客户反馈要求数据中心不再渲染维度下钻面板");
assert(source.includes("function CustomerDimensionTags"), "CRM 客户区域/类型必须使用统一标签组件");
assert(source.includes('headers={["项目", "客户", "负责人", "标签"'), "CRM 数据中心下钻明细的区域/类型列应改为标签列");
assert(source.includes("<CustomerDimensionTags region={row.region} customerType={row.customer_type} compact"), "CRM 数据中心下钻明细必须用区域/类型标签展示");
assert(!source.includes('className="mb-4 grid gap-3 xl:grid-cols-6"'), "CRM 数据中心不能继续使用六列高维度卡布局");
assert(!source.includes("<CrmDataCenterDimension title="), "CRM 数据中心不能继续直接堆叠旧维度卡");

console.log("CRM 数据中心精简布局检查通过");
