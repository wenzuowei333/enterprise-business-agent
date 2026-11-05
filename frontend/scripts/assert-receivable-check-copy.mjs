import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = readFileSync(resolve("src/App.tsx"), "utf8");
const start = source.indexOf("function ReceivableCheckPanel");
const end = source.indexOf("const accountLedgerRoleLabels");

if (start === -1 || end === -1 || end <= start) {
  throw new Error("Unable to locate receivable check UI block.");
}

const receivableCheckBlock = source.slice(start, end);

const requiredCopy = [
  "往来明细",
  "应收查询",
  "应收校验",
  "应收校验差异",
  "应收查询校验",
  "ReceivableSnapshotPanel",
  "系统按结算单位编号/名称，将应收查询表与往来明细期初/期末应收进行比对。",
  "应收查询金额",
  "往来明细应收"
];

for (const text of requiredCopy) {
  if (!receivableCheckBlock.includes(text)) {
    throw new Error(`Missing receivable check copy: ${text}`);
  }
}

const forbiddenCopy = [
  "近30天销售",
  "近 30 天销售",
  "销售后仍欠款",
  "欠款供货",
  "supply_with_debt",
  "应收底数",
  "客户主档",
  "上期应收",
  "账龄异常",
  "customer_unmatched",
  "account_balance_mismatch",
  "ar_increased",
  "aging_risk",
  "往来明细期末应收"
];

for (const text of forbiddenCopy) {
  if (receivableCheckBlock.includes(text)) {
    throw new Error(`Forbidden receivable check copy remains: ${text}`);
  }
}

const accountBalanceBlockStart = source.indexOf("function AccountBalancePage");
const accountBalanceBlockEnd = source.indexOf("function ReceivableSnapshotPanel");
const accountBalanceBlock = source.slice(accountBalanceBlockStart, accountBalanceBlockEnd);
const forbiddenAccountBalanceCopy = [
  'setActiveTab("receivable")',
  'activeTab === "receivable"',
  '>应收查询</button>'
];

for (const text of forbiddenAccountBalanceCopy) {
  if (accountBalanceBlock.includes(text)) {
    throw new Error(`Receivable query must not remain as a top-level account tab: ${text}`);
  }
}

console.log("Receivable check copy contract OK");
