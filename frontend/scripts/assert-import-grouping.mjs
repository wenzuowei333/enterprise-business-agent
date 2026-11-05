import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = readFileSync(resolve("src/App.tsx"), "utf8");

const requiredSnippets = [
  'const processImportTypes: Array<{ value: ProcessImportType; label: string; permission?: PermissionCode }> = [',
  '{ value: "sales_detail", label: "销售明细"',
  '{ value: "purchase_detail", label: "采购明细"',
  '{ value: "account_ledger", label: "往来明细"',
  'const blockedGenericImportTypes = new Set(["inventory_snapshot", "inventory_check", "receivable_snapshot"])',
  'form.set("file_type", "receivable_snapshot")',
  "应收查询表请到「往来对账 -> 应收校验」页面上传",
  "库存核验请到「库存快照 -> 库存校验」页面上传",
  "过程数据",
  "应收查询表"
];

for (const snippet of requiredSnippets) {
  if (!source.includes(snippet)) {
    throw new Error(`Missing import grouping contract: ${snippet}`);
  }
}

const processBlock = source.slice(
  source.indexOf("const processImportTypes"),
  source.indexOf("const blockedGenericImportTypes")
);

for (const forbidden of ['"inventory_snapshot"', '"account_balance"', '"receivable_snapshot"']) {
  if (processBlock.includes(forbidden)) {
    throw new Error(`Process import group must not expose ${forbidden}`);
  }
}

const importDrawerBlock = source.slice(
  source.indexOf("function MasterDataImportDrawer"),
  source.indexOf("function ImportBatchSummary")
);

for (const forbidden of ["verificationImportTypes", '<optgroup label=\"核验数据\">', "uploadInventoryCheck(form)"]) {
  if (importDrawerBlock.includes(forbidden)) {
    throw new Error(`Generic import drawer must not expose verification import flow: ${forbidden}`);
  }
}

console.log("Import grouping contract OK");
