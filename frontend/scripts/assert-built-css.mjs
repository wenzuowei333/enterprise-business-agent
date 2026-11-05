import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const staticRoot = resolve(scriptDir, "../../backend/app/static/react");
const indexHtml = readFileSync(resolve(staticRoot, "index.html"), "utf8");
const stylesheetMatch = indexHtml.match(/href="\/static\/react\/(assets\/[^\"]+\.css)"/);

assert.ok(stylesheetMatch, "构建后的 index.html 必须引用带哈希的 CSS 文件");

const css = readFileSync(resolve(staticRoot, stylesheetMatch[1]), "utf8");

assert.ok(css.length > 50_000, "构建 CSS 体积异常，Tailwind 工具类可能没有生成");
assert.ok(!css.includes("@tailwind"), "构建 CSS 仍包含 @tailwind，PostCSS 未执行");
assert.ok(!css.includes("@apply"), "构建 CSS 仍包含 @apply，Tailwind 未展开组件样式");
assert.match(css, /\.flex\{display:flex\}/, "构建 CSS 缺少常用 Tailwind 工具类");

console.log(`Built CSS verified: ${stylesheetMatch[1]} (${css.length} bytes)`);
