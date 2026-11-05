import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const builtIndex = resolve("../backend/app/static/react/index.html");
const source = readFileSync(builtIndex, "utf8");
const normalized = source.replace(/\r+\n/g, "\n").replace(/\r/g, "\n");

if (source !== normalized) writeFileSync(builtIndex, normalized, "utf8");
console.log(`Built HTML line endings verified: ${builtIndex}`);
