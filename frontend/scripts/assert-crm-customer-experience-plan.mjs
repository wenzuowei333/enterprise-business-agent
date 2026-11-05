import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd());
const app = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(root, "src", "api", "client.ts"), "utf8");

const expectations = [
  [client, "recommended_products?: CustomerRecommendedProductPayload[]", "API 类型需要支持拜访推荐产品 payload"],
  [client, "current_flow_node?: string | null", "关联客户行需要返回当前流程节点"],
  [client, "flow_nodes?: CrmCustomerFlowNode[]", "客户上下文需要返回流程节点"],
  [app, "本次拜访推荐产品", "经营资料提交抽屉需要展示拜访推荐产品区块"],
  [app, "addRecommendedProduct", "经营资料提交抽屉需要支持新增推荐产品行"],
  [app, "项目分配", "主数据客户列表需要展示项目分配状态"],
  [app, "资料缺失", "主数据客户列表需要资料缺失筛选"],
  [app, "流程进度", "关联客户底盘需要展示流程进度"],
  [app, "current_flow_node", "CRM 关联客户列表需要展示当前节点字段"],
  [app, "missing_business_profile", "客户分页请求需要传递缺经营资料筛选参数"]
];

const missing = expectations
  .filter(([source, needle]) => !source.includes(needle))
  .map(([, , message]) => message);

if (missing.length > 0) {
  console.error(["CRM 客户体验断言失败：", ...missing.map((item) => `- ${item}`)].join("\n"));
  process.exit(1);
}

console.log("CRM customer experience assertions passed.");
