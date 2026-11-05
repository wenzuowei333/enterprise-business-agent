import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (path) => readFileSync(resolve(path), "utf8");
const app = read("src/App.tsx");
const styles = read("src/styles.css");
const designSystem = read("src/design-system/index.tsx");
const motionTokens = read("src/design-system/motion.ts");
const crmEntrance = read("src/components/crm/CrmWorkbenchEntrance.tsx");
const crmMotionController = read("src/components/crm/CrmWorkbenchMotionController.tsx");
const playwrightConfig = read("playwright.config.ts");
const workflow = read("../.github/workflows/ci.yml");
const packageJson = JSON.parse(read("package.json"));

assert.equal(packageJson.dependencies.gsap, "3.15.0", "GSAP runtime version must remain pinned");
assert.equal(packageJson.dependencies["@gsap/react"], "2.1.2", "GSAP React integration must remain pinned");
assert.match(playwrightConfig, /testMatch:\s*"\*\.spec\.ts"/, "Playwright must collect every browser regression spec");
assert.ok(workflow.includes("npm run build") && workflow.includes("npm run test:assertions") && workflow.includes("npm run test:e2e"), "CI must gate frontend delivery on build, source contracts and browser tests");

for (const contract of [
  'export type Tone = "info" | "success" | "warning" | "danger" | "neutral"',
  'export type Density = "comfortable" | "compact"',
  'data-ui="page-header"',
  'data-ui="button"',
  'data-ui="badge"',
  'data-ui="tabs"',
  'data-ui="toolbar"',
  'data-ui="stat-strip"',
  'data-ui="data-table-shell"',
  'data-ui="empty-state"'
]) {
  assert.ok(designSystem.includes(contract), `Design-system contract missing: ${contract}`);
}

for (const contract of [
  'export type MotionPreset = "instant" | "fast" | "standard" | "deliberate"',
  "instant: 120",
  "fast: 160",
  "standard: 220",
  "deliberate: 280",
  "feedback: 4",
  "enter: 8",
  "panel: 48",
  "totalDuration: 0.44",
  "stagger: 0.035",
  "maxStaggerItems: 6"
]) {
  assert.ok(motionTokens.includes(contract), `Motion token contract missing: ${contract}`);
}

for (const contract of [
  "--background: 216 38% 97.45%",
  "--primary: 221 83% 53%",
  "--brand-support: 175 77% 26%",
  "--radius-lg: 0.5rem",
  "--space-1: 0.25rem",
  "--space-8: 2rem",
  "--font-page-title: 1.5rem",
  "--font-body: 0.875rem",
  "--motion-duration-fast: 160ms",
  "--motion-distance-panel: 48px"
]) {
  assert.ok(styles.includes(contract), `Visual token missing: ${contract}`);
}

assert.ok(styles.includes(".app-sidebar") && styles.includes("w-56"), "Expanded desktop navigation must remain 224px wide");
assert.ok(styles.includes('.app-sidebar[data-collapsed="true"]') && styles.includes("w-16"), "Collapsed desktop navigation must remain 64px wide");
assert.ok(!/\.app-sidebar\s*\{[^}]*transition:\s*width/s.test(styles), "Framer must remain the only sidebar width animation owner");
assert.ok(app.includes('data-testid="app-sidebar"') && app.includes('data-testid="app-workspace"'), "Production shell must expose stable navigation and workspace test contracts");
assert.ok(app.includes('project.shell.left-expanded.v1'), "Production shell must persist the navigation width preference");
assert.ok(!app.includes('<h1 className="crm-shell-title">客户 CRM</h1>'), "CRM module navigation must not repeat the global module title");
assert.ok(!app.includes('<h1 className="m-0 truncate text-base font-black text-foreground">{activeItem.label}</h1>'), "The global module context must not compete with the page H1");

assert.ok(crmEntrance.includes('from "@gsap/react"') && crmEntrance.includes('from "gsap"'), "CRM entrance must use the official React GSAP integration");
assert.ok(crmEntrance.includes("gsap.registerPlugin(useGSAP)"), "useGSAP must be registered before use");
assert.ok(crmEntrance.includes("useGSAP("), "CRM entrance must use useGSAP for lifecycle cleanup");
assert.ok(crmEntrance.includes("scope: scopeRef"), "GSAP selectors must be scoped to the CRM workbench");
assert.ok(crmEntrance.includes('[data-crm-enter]'), "CRM entrance must only target explicit workbench elements");
assert.ok(crmEntrance.includes("gsap.matchMedia()"), "CRM entrance must isolate reduced-motion behavior with gsap.matchMedia");
assert.ok(crmEntrance.includes("(prefers-reduced-motion: no-preference)"), "GSAP matchMedia must also run for users who allow motion");
assert.ok(crmEntrance.includes("clearProps"), "Completed and interrupted animations must clear inline GSAP styles");
assert.ok(crmEntrance.includes('"full"') && crmEntrance.includes('"repeat"') && crmEntrance.includes('"reduced"') && crmEntrance.includes('"complete"'), "CRM entrance must expose every observable motion state");

assert.ok(crmMotionController.includes('import("./CrmWorkbenchEntrance")'), "GSAP must load through a CRM-only lazy chunk");
assert.ok(crmMotionController.includes("try") && crmMotionController.includes("catch"), "CRM must remain usable when its optional motion chunk fails");
assert.ok(crmMotionController.includes("FAIL_OPEN_DELAY_MS"), "A delayed motion chunk must reveal CRM content without waiting indefinitely");
const homeStart = app.indexOf("function CrmStandardHomeSection");
const homeEnd = app.indexOf("function CrmHomeEntryGroup", homeStart);
assert.ok(homeStart >= 0 && homeEnd > homeStart, "Unable to isolate the CRM standard home implementation");
const home = app.slice(homeStart, homeEnd);
assert.ok(home.includes('data-testid="crm-workbench"'), "CRM home must expose its workbench root");
assert.ok(home.includes('data-testid="crm-today-queue"'), "CRM home must expose the five-item today queue");
assert.ok(home.includes('data-testid="crm-workspace-groups"'), "CRM home must expose the three work groups");
assert.ok(home.includes("CrmWorkbenchMotionController"), "CRM home must mount its fail-open lazy entrance controller");
assert.ok(!home.includes("常用动作"), "Common actions must remain in the page header instead of a separate card");
for (const queueLabel of ["继续草稿", "待我补充", "客户资料", "待我审批", "待我支持"]) {
  assert.ok(home.includes(queueLabel), `CRM today queue is missing: ${queueLabel}`);
}

console.log("UI visual foundation and CRM motion source contracts passed.");
