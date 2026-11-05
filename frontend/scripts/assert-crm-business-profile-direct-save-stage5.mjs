import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd());
const app = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(root, "src", "api", "client.ts"), "utf8");

function assertIncludes(source, needle, message) {
  if (!source.includes(needle)) throw new Error(message);
}

function assertNotIncludes(source, needle, message) {
  if (source.includes(needle)) throw new Error(message);
}

assertIncludes(app, 'label: "经营资料填写"', "业务执行入口需要统一命名为经营资料填写");
assertIncludes(app, 'title="经营资料填写"', "经营资料页面和抽屉需要使用填写口径");
assertIncludes(app, "保存后立即同步主数据", "经营资料页面需要明确直存结果");
assertIncludes(client, "updateCrmLinkedCustomerBusinessProfile", "客户端需要保留经营资料直接保存接口");
assertIncludes(client, "/business-profile/update", "经营资料保存必须调用直接更新接口");
assertNotIncludes(client, "createCrmBusinessProfileApprovalDraft", "客户端不能继续暴露经营资料审批创建方法");
assertNotIncludes(client, "/business-profile/approval-draft", "客户端不能继续调用经营资料审批草稿接口");
assertNotIncludes(app, "经营资料更新会流转给该人员审批", "项目人员说明不能继续宣称经营资料需要审批");
assertNotIncludes(app, "经营资料提交", "阶段 5 用户界面需要清除经营资料提交旧术语");

console.log("CRM 经营资料直接保存阶段 5 断言通过");
