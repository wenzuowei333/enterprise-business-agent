import assert from "node:assert/strict";
import { gzipSync } from "node:zlib";
import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";

const staticRoot = resolve("../backend/app/static/react");
const assetsRoot = resolve(staticRoot, "assets");
const indexHtml = readFileSync(resolve(staticRoot, "index.html"), "utf8");
const entryMatch = indexHtml.match(/<script[^>]+src="\/static\/react\/(assets\/[^"]+\.js)"/);
assert.ok(entryMatch, "Built application entry script was not found");

const entryName = basename(entryMatch[1]);
const javascriptFiles = readdirSync(assetsRoot).filter((name) => name.endsWith(".js"));
const entrySource = readFileSync(resolve(assetsRoot, entryName), "utf8");
const entryCompressedBytes = gzipSync(Buffer.from(entrySource)).byteLength;
assert.ok(
  entryCompressedBytes <= 565 * 1024,
  `Application entry is ${entryCompressedBytes} compressed bytes; budget is ${565 * 1024}`,
);
assert.ok(!entrySource.includes("3.15.0"), "GSAP must not be bundled into the global application entry");

const gsapChunks = javascriptFiles
  .filter((name) => name !== entryName)
  .map((name) => ({ name, source: readFileSync(resolve(assetsRoot, name), "utf8") }))
  .filter(({ source }) => source.includes("3.15.0"));

assert.equal(gsapChunks.length, 1, `Expected one isolated GSAP chunk, found ${gsapChunks.length}`);
const compressedBytes = gzipSync(Buffer.from(gsapChunks[0].source)).byteLength;
assert.ok(compressedBytes <= 32 * 1024, `GSAP CRM chunk is ${compressedBytes} compressed bytes; budget is 32768`);

console.log(`Bundle budgets passed: ${entryName} (${entryCompressedBytes} gzip bytes), ${gsapChunks[0].name} (${compressedBytes} gzip bytes).`);
