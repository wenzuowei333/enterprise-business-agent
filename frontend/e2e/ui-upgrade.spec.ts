import { expect, test, type Page } from "@playwright/test";

const testPort = process.env.PW_PORT || "4173";

type MotionAudit = {
  states: Array<{ value: string; time: number }>;
  transforms: Array<{ value: string; time: number }>;
};

const viewports = [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1366, height: 768 },
  { width: 1024, height: 768 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 }
] as const;

async function installMotionAudit(page: Page) {
  await page.addInitScript(() => {
    const audit: MotionAudit = { states: [], transforms: [] };
    (window as typeof window & { __crmMotionAudit?: MotionAudit }).__crmMotionAudit = audit;
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        if (!(record.target instanceof HTMLElement)) continue;
        if (record.attributeName === "data-motion-state") {
          audit.states.push({ value: record.target.dataset.motionState ?? "", time: performance.now() });
        }
        if (record.attributeName === "style" && record.target.matches("[data-crm-enter]")) {
          const transform = record.target.style.transform;
          if (transform) audit.transforms.push({ value: transform, time: performance.now() });
        }
      }
    });
    observer.observe(document, { subtree: true, attributes: true, attributeFilter: ["data-motion-state", "style"] });
  });
}

async function openUiHarness(page: Page, width = 1366, height = 768) {
  await page.setViewportSize({ width, height });
  await page.goto("ui-upgrade-harness.html");
  await expect(page.getByTestId("crm-workbench")).toHaveAttribute("data-motion-state", "complete");
}

async function motionAudit(page: Page) {
  return page.evaluate(() => (window as typeof window & { __crmMotionAudit: MotionAudit }).__crmMotionAudit);
}

async function assertNoEntranceInlineStyles(page: Page) {
  const inlineStyles = await page.locator("[data-crm-enter]").evaluateAll((elements) => elements.map((element) => {
    const node = element as HTMLElement;
    return {
      opacity: node.style.opacity,
      transform: node.style.transform,
      visibility: node.style.visibility
    };
  }));
  expect(inlineStyles).toEqual(inlineStyles.map(() => ({ opacity: "", transform: "", visibility: "" })));
}

test.beforeEach(async ({ page }) => {
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "127.0.0.1" && url.port === testPort && !url.pathname.startsWith("/api/")) await route.continue();
    else await route.abort("blockedbyclient");
  });
  await installMotionAudit(page);
});

test("global shell and CRM workbench expose stable dense-workspace contracts", async ({ page }) => {
  await openUiHarness(page);

  const sidebar = page.getByTestId("app-sidebar");
  await expect(sidebar).toHaveAttribute("data-collapsed", "true");
  await expect.poll(async () => (await sidebar.boundingBox())?.width).toBeCloseTo(64, 0);
  await expect(page.locator("h1")).toHaveCount(1);
  await expect(page.locator("h1")).toHaveText("今日工作台");
  await expect(page.getByTestId("crm-today-queue")).toBeVisible();
  await expect(page.getByTestId("crm-today-queue").locator(".crm-workbench-queue-item")).toHaveCount(5);
  await expect(page.getByTestId("crm-workspace-groups").locator(":scope > section")).toHaveCount(3);
  await expect(page.locator("[data-crm-enter]")).toHaveCount(5);

  await page.getByTestId("toggle-sidebar").click();
  await expect(sidebar).toHaveAttribute("data-collapsed", "false");
  await expect.poll(async () => (await sidebar.boundingBox())?.width).toBeCloseTo(224, 0);
  await page.reload();
  await expect(page.getByTestId("app-sidebar")).toHaveAttribute("data-collapsed", "false");
});

for (const viewport of viewports) {
  test(`upgraded workspace remains contained at ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await openUiHarness(page, viewport.width, viewport.height);

    const documentWidth = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
    expect(documentWidth.scroll - documentWidth.client).toBeLessThanOrEqual(1);

    const mainBox = await page.getByTestId("main-content").boundingBox();
    expect(mainBox).not.toBeNull();
    expect(mainBox!.x).toBeGreaterThanOrEqual(-1);
    expect(mainBox!.x + mainBox!.width).toBeLessThanOrEqual(viewport.width + 1);

    const groupsBox = await page.getByTestId("crm-workspace-groups").boundingBox();
    expect(groupsBox).not.toBeNull();
    if (viewport.width === 1366) expect(groupsBox!.y).toBeLessThan(viewport.height - 120);

    const headerTitle = await page.locator(".crm-workbench-title").boundingBox();
    const headerActions = await page.locator(".crm-workbench-actions").boundingBox();
    expect(headerTitle).not.toBeNull();
    expect(headerActions).not.toBeNull();
    if (headerTitle!.y < headerActions!.y + headerActions!.height && headerActions!.y < headerTitle!.y + headerTitle!.height) {
      expect(headerTitle!.x + headerTitle!.width).toBeLessThanOrEqual(headerActions!.x + 1);
    }

    if (viewport.width === 1366) {
      const queueBox = await page.getByTestId("crm-today-queue").boundingBox();
      expect(queueBox).not.toBeNull();
      expect(queueBox!.y + queueBox!.height).toBeLessThanOrEqual(viewport.height);
      const firstEntries = page.getByTestId("crm-workspace-groups").locator(".crm-workbench-group .crm-workbench-entry:first-child");
      await expect(firstEntries).toHaveCount(3);
      for (const entry of await firstEntries.all()) {
        const box = await entry.boundingBox();
        expect(box).not.toBeNull();
        expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
      }
    }

    await page.screenshot({ path: testInfo.outputPath(`ui-upgrade-${viewport.width}x${viewport.height}.png`), fullPage: false });
  });
}

test("GSAP full and repeat entrances finish within their budgets and clear inline styles", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("ui-upgrade-harness.html");
  await page.evaluate(() => window.sessionStorage.clear());
  await page.reload();
  await expect(page.getByTestId("crm-workbench")).toHaveAttribute("data-motion-state", "complete");

  const fullAudit = await motionAudit(page);
  const fullStart = fullAudit.states.find((entry) => entry.value === "full");
  const fullEnd = fullAudit.states.findLast((entry) => entry.value === "complete");
  expect(fullStart).toBeDefined();
  expect(fullEnd).toBeDefined();
  expect(fullEnd!.time - fullStart!.time).toBeLessThanOrEqual(650);
  expect(fullAudit.transforms.length).toBeGreaterThan(0);
  await assertNoEntranceInlineStyles(page);

  await page.reload();
  await expect(page.getByTestId("crm-workbench")).toHaveAttribute("data-motion-state", "complete");
  const repeatAudit = await motionAudit(page);
  const repeatStart = repeatAudit.states.find((entry) => entry.value === "repeat");
  const repeatEnd = repeatAudit.states.findLast((entry) => entry.value === "complete");
  expect(repeatStart).toBeDefined();
  expect(repeatEnd).toBeDefined();
  expect(repeatEnd!.time - repeatStart!.time).toBeLessThanOrEqual(300);
  expect(repeatAudit.transforms).toHaveLength(0);
  await assertNoEntranceInlineStyles(page);
});

test("reduced motion never applies movement and completes as a short opacity transition", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("ui-upgrade-harness.html");
  await page.evaluate(() => window.sessionStorage.clear());
  await page.reload();
  await expect(page.getByTestId("crm-workbench")).toHaveAttribute("data-motion-state", "complete");

  const audit = await motionAudit(page);
  const start = audit.states.find((entry) => entry.value === "reduced");
  const end = audit.states.findLast((entry) => entry.value === "complete");
  expect(start).toBeDefined();
  expect(end).toBeDefined();
  expect(end!.time - start!.time).toBeLessThanOrEqual(220);
  expect(audit.transforms).toHaveLength(0);
  await assertNoEntranceInlineStyles(page);
});

test("CRM remains usable when the optional GSAP chunk fails to load", async ({ page }) => {
  const pageErrors: Error[] = [];
  page.on("pageerror", (error) => pageErrors.push(error));
  await page.route("**/src/components/crm/CrmWorkbenchEntrance.tsx*", (route) => route.abort("failed"));
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("ui-upgrade-harness.html");

  await expect(page.getByTestId("crm-workbench")).toHaveAttribute("data-motion-state", "complete");
  await expect(page.getByRole("heading", { name: "今日工作台" })).toBeVisible();
  await expect(page.getByRole("button", { name: "项目申请" })).toBeEnabled();
  expect(pageErrors).toEqual([]);
});

test("a slow optional GSAP chunk reveals CRM before it finishes loading", async ({ page }) => {
  await page.route("**/src/components/crm/CrmWorkbenchEntrance.tsx*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 900));
    await route.continue();
  });
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("ui-upgrade-harness.html", { waitUntil: "domcontentloaded" });

  const workbench = page.getByTestId("crm-workbench");
  await expect(workbench).toHaveAttribute("data-motion-state", "skipped", { timeout: 800 });
  await expect(page.getByRole("heading", { name: "今日工作台" })).toBeVisible();
  await expect(workbench).toHaveAttribute("data-motion-state", "complete", { timeout: 3_000 });
  expect((await motionAudit(page)).transforms).toHaveLength(0);
});

test("GSAP controller can repeatedly unmount without leaving inline styles", async ({ page }) => {
  await openUiHarness(page);
  const controller = page.getByTestId("toggle-motion-controller");

  for (let index = 0; index < 10; index += 1) {
    await controller.evaluate((button: HTMLButtonElement) => button.click());
    await expect(page.getByTestId("crm-workbench")).toHaveAttribute("data-controller-mounted", "false");
    await assertNoEntranceInlineStyles(page);
    await controller.evaluate((button: HTMLButtonElement) => button.click());
    await expect(page.getByTestId("crm-workbench")).toHaveAttribute("data-motion-state", "complete");
  }

  await controller.evaluate((button: HTMLButtonElement) => button.click());
  await assertNoEntranceInlineStyles(page);
});

test("overlay stack survives twenty rapid open-close cycles", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("drawer-harness.html");

  for (let index = 0; index < 20; index += 1) {
    await page.getByTestId("open-primary").click();
    await expect(page.locator('[data-overlay-kind="drawer"]')).toHaveCount(1);
    await page.locator(".project-drawer-close").click();
    await expect(page.locator('[data-overlay-kind="drawer"]')).toHaveCount(0);
  }

  await expect(page.locator("[data-overlay-kind]")).toHaveCount(0);
  await expect(page.locator("#app")).not.toHaveAttribute("inert", "");
  expect(await page.evaluate(() => document.body.style.position)).toBe("");
});
