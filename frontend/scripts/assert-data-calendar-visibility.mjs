import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = readFileSync(resolve("src/App.tsx"), "utf8");
const blockStart = source.indexOf("function DataActionCalendar(");
const blockEnd = source.indexOf("function DataCalendarRuleDrawer(", blockStart);
const calendarSource = source.slice(blockStart, blockEnd);

const requiredSnippets = [
  "const userRows = await users().catch(() => []);",
  "setRows(batchRows);",
  "setCoverageRows(coverage);",
  "setCalendarUsers(userRows);"
];

for (const snippet of requiredSnippets) {
  if (!calendarSource.includes(snippet)) {
    throw new Error(`数据日历必须在无账号查看权限时保留已加载的覆盖数据：${snippet}`);
  }
}

console.log("Data calendar visibility contract OK");
