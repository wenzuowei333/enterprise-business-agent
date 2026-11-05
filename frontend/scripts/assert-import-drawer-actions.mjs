import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = readFileSync(resolve("src/App.tsx"), "utf8");

const masterDataImportDrawerBlock = source.slice(
  source.indexOf("function MasterDataImportDrawer"),
  source.indexOf("function ImportBatchSummary")
);
const flowStart = masterDataImportDrawerBlock.indexOf('{activeTab === "flow" ? (');
const asideStart = masterDataImportDrawerBlock.indexOf('<aside className="grid content-start gap-3">', flowStart);
const importDrawerBlock = masterDataImportDrawerBlock.slice(flowStart, asideStart);

if (!importDrawerBlock.includes("MasterDataImportActionBar")) {
  throw new Error("导入抽屉需要使用独立操作条，避免提交入库按钮被布局挤出。");
}

if (importDrawerBlock.includes("2xl:grid-cols-[minmax(0,1fr)_320px]")) {
  throw new Error("导入抽屉不能按浏览器 2xl 断点启用双栏；抽屉宽度较窄时会遮挡提交入库按钮。");
}

if (importDrawerBlock.includes("xl:grid-cols-[minmax(0,1fr)_360px]")) {
  throw new Error("导入抽屉不应在 xl 宽度强制 360px 右栏，容易隐藏提交入库按钮。");
}

if (!importDrawerBlock.includes('<div className="grid gap-4">')) {
  throw new Error("导入操作区应保持单栏布局，让提交入库按钮始终留在主流程下方。");
}

console.log("Import drawer action layout contract OK");
