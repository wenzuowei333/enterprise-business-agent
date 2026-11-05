import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const scriptsDirectory = dirname(fileURLToPath(import.meta.url));
const assertionFiles = readdirSync(scriptsDirectory)
  .filter((name) => name.startsWith("assert-") && name.endsWith(".mjs"))
  .sort();

const failures = [];
for (const file of assertionFiles) {
  console.log(`[ASSERT] ${file}`);
  const result = spawnSync(process.execPath, [join(scriptsDirectory, file)], {
    cwd: join(scriptsDirectory, ".."),
    stdio: "inherit"
  });
  if (result.status !== 0) failures.push(file);
}

if (failures.length > 0) {
  console.error(`Failed assertions: ${failures.join(", ")}`);
  process.exit(1);
}

console.log(`All ${assertionFiles.length} frontend assertions passed.`);
