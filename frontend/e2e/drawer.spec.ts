import { expect, test, type Page } from "@playwright/test";

const testPort = process.env.PW_PORT || "4173";

const DRAWER = '[data-overlay-kind="drawer"]';
const TOP_DRAWER_PANEL = `${DRAWER}[data-overlay-top="true"] .project-drawer-panel`;

async function openHarness(page: Page, width: number, height: number) {
  await page.setViewportSize({ width, height });
  await page.goto("drawer-harness.html");
  await page.evaluate(() => window.localStorage.clear());
  await page.reload();
  await expect(page.getByTestId("open-primary")).toBeVisible();
}

async function waitForPanelSettled(page: Page) {
  const panel = page.locator(TOP_DRAWER_PANEL);
  await panel.evaluate((element) => new Promise<void>((resolve, reject) => {
    const deadline = performance.now() + 3_000;
    let previousRight: number | null = null;
    let stableFrames = 0;

    const check = (now: number) => {
      const right = element.getBoundingClientRect().right;
      const edgeError = Math.abs(right - window.innerWidth);
      const frameDelta = previousRight === null ? Number.POSITIVE_INFINITY : Math.abs(right - previousRight);
      stableFrames = edgeError <= 1 && frameDelta <= 0.1 ? stableFrames + 1 : 0;
      previousRight = right;

      if (stableFrames >= 5) {
        resolve();
        return;
      }
      if (now >= deadline) {
        reject(new Error(`Drawer did not settle at the right viewport edge; last error was ${edgeError.toFixed(2)}px.`));
        return;
      }
      window.requestAnimationFrame(check);
    };

    window.requestAnimationFrame(check);
  }));
}

async function openPrimary(page: Page) {
  await page.getByTestId("open-primary").click();
  const panel = page.locator(TOP_DRAWER_PANEL);
  await expect(panel).toBeVisible();
  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  await waitForPanelSettled(page);
  return panel;
}

async function panelBox(page: Page) {
  const box = await page.locator(TOP_DRAWER_PANEL).boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

test.beforeEach(async ({ page }) => {
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "127.0.0.1" && url.port === testPort && !url.pathname.startsWith("/api/")) await route.continue();
    else await route.abort("blockedbyclient");
  });
});

test("desktop drawer grows left, persists, maximizes and resets", async ({ page }, testInfo) => {
  await openHarness(page, 1920, 1080);
  const panel = await openPrimary(page);
  const initial = await panelBox(page);
  expect(initial.width).toBeGreaterThan(1450);
  expect(Math.abs(initial.x + initial.width - 1920)).toBeLessThanOrEqual(1);

  const handle = page.locator(`${DRAWER}[data-overlay-top="true"] .project-drawer-resize-handle`);
  const handleBox = await handle.boundingBox();
  expect(handleBox).not.toBeNull();

  await page.mouse.move(handleBox!.x + handleBox!.width / 2, handleBox!.y + 260);
  await page.mouse.down();
  await page.mouse.move(handleBox!.x - 120, handleBox!.y + 260, { steps: 4 });
  await expect.poll(async () => (await panelBox(page)).width).toBeGreaterThan(initial.width + 80);
  await expect(panel).toHaveAttribute("data-resizing", "true");
  await page.keyboard.press("Escape");
  await page.mouse.up();
  await expect(page.locator(DRAWER)).toHaveCount(1);
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(initial.width, 0);

  await page.mouse.move(handleBox!.x + handleBox!.width / 2, handleBox!.y + 260);
  await page.mouse.down();
  await page.mouse.move(handleBox!.x - 240, handleBox!.y + 260, { steps: 8 });
  await page.mouse.up();

  await expect.poll(async () => (await panelBox(page)).width).toBeGreaterThan(initial.width + 200);
  const expanded = await panelBox(page);
  expect(Math.abs(expanded.x + expanded.width - 1920)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: testInfo.outputPath("drawer-1920-drag-expanded.png"), fullPage: false });

  const expandedHandleBox = await handle.boundingBox();
  expect(expandedHandleBox).not.toBeNull();
  await page.mouse.move(expandedHandleBox!.x + expandedHandleBox!.width / 2, expandedHandleBox!.y + 260);
  await page.mouse.down();
  await page.mouse.move(expandedHandleBox!.x + 120, expandedHandleBox!.y + 260, { steps: 4 });
  await page.mouse.up();
  await expect.poll(async () => (await panelBox(page)).width).toBeLessThan(expanded.width - 80);
  const adjusted = await panelBox(page);

  await page.getByRole("button", { name: "关闭" }).click();
  await expect(page.locator(DRAWER)).toHaveCount(0);
  await page.getByTestId("open-primary").click();
  await waitForPanelSettled(page);
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(adjusted.width, 0);

  await page.setViewportSize({ width: 1366, height: 768 });
  await waitForPanelSettled(page);
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(1342, 0);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await waitForPanelSettled(page);
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(adjusted.width, 0);

  await page.getByRole("button", { name: "最大化抽屉" }).click();
  await expect.poll(async () => (await panelBox(page)).width).toBeGreaterThan(1880);
  await page.setViewportSize({ width: 1366, height: 768 });
  await waitForPanelSettled(page);
  await page.getByRole("button", { name: "恢复抽屉宽度" }).click();
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(1342, 0);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await waitForPanelSettled(page);
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(adjusted.width, 0);

  await handle.dblclick();
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(1498, -1);
});

test("separator keyboard sizing obeys steps and clamps", async ({ page }) => {
  await openHarness(page, 1440, 900);
  await openPrimary(page);
  const handle = page.locator(`${DRAWER}[data-overlay-top="true"] .project-drawer-resize-handle`);
  await handle.focus();
  const initial = await panelBox(page);

  await handle.press("ArrowRight");
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(initial.width - 24, 0);
  await handle.press("Shift+ArrowLeft");
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(initial.width + 72, 0);
  await handle.press("Home");
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(720, 0);
  await expect(handle).toHaveAttribute("aria-valuenow", "720");
  const legacyColumnsAtMinimum = await page.getByTestId("legacy-grid").evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length);
  expect(legacyColumnsAtMinimum).toBe(2);
  await handle.press("End");
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(1416, 0);
  await expect(handle).toHaveAttribute("aria-valuemax", "1416");
});

for (const viewport of [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1366, height: 768 },
  { width: 1024, height: 768 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 }
]) {
  test(`responsive content remains contained at ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await openHarness(page, viewport.width, viewport.height);
    await openPrimary(page);
    const panel = await panelBox(page);
    expect(Math.abs(panel.x + panel.width - viewport.width)).toBeLessThanOrEqual(1);

    const handle = page.locator(".project-drawer-resize-handle");
    const sizeToggle = page.locator(".project-drawer-size-toggle");
    if (viewport.width < 1024) {
      expect(Math.abs(panel.width - viewport.width)).toBeLessThanOrEqual(1);
      await expect(handle).toBeHidden();
      await expect(sizeToggle).toBeHidden();
    } else {
      await expect(handle).toBeVisible();
      await expect(sizeToggle).toBeVisible();
    }

    const layout = await page.getByTestId("drawer-split").evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length);
    const metrics = await page.getByTestId("metric-grid").evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length);
    const legacyColumns = await page.getByTestId("legacy-grid").evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length);
    const permissionColumns = await page.getByTestId("permission-grid").evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length);
    expect(layout).toBe(panel.width >= 1100 ? 2 : 1);
    expect(metrics).toBe(panel.width >= 1280 ? 4 : panel.width >= 720 ? 2 : 1);
    expect(legacyColumns).toBe(panel.width >= 1280 ? 4 : panel.width >= 720 ? 2 : 1);
    expect(permissionColumns).toBe(panel.width >= 1280 ? 3 : panel.width >= 1100 ? 2 : 1);

    const containment = await page.locator(".project-drawer-body").evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth }));
    expect(containment.scroll - containment.client).toBeLessThanOrEqual(1);
    const table = await page.getByTestId("wide-table-region").evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth }));
    if (panel.width < 1000) expect(table.scroll).toBeGreaterThan(table.client);

    const actionsBox = await page.getByTestId("sticky-actions").boundingBox();
    expect(actionsBox).not.toBeNull();
    expect(actionsBox!.x).toBeGreaterThanOrEqual(panel.x - 1);
    expect(actionsBox!.x + actionsBox!.width).toBeLessThanOrEqual(panel.x + panel.width + 1);

    const titleBox = await page.locator(".project-drawer-title").boundingBox();
    const headerActionsBox = await page.locator(".project-drawer-header-actions").boundingBox();
    expect(titleBox).not.toBeNull();
    expect(headerActionsBox).not.toBeNull();
    expect(titleBox!.x + titleBox!.width).toBeLessThanOrEqual(headerActionsBox!.x + 1);

    if (viewport.width === 390 || viewport.width === 1920) {
      await page.screenshot({ path: testInfo.outputPath(`drawer-${viewport.width}.png`), fullPage: false });
    }
  });
}

test("nested drawers close one layer at a time and restore focus", async ({ page }) => {
  await openHarness(page, 1920, 1080);
  await openPrimary(page);
  await page.getByTestId("open-nested").click();
  await expect(page.locator(DRAWER)).toHaveCount(2);
  await page.getByTestId("open-third").click();
  await expect(page.locator(DRAWER)).toHaveCount(3);

  const zIndexes = await page.locator(DRAWER).evaluateAll((elements) => elements.map((element) => Number(getComputedStyle(element).zIndex)));
  expect(zIndexes[0]).toBeLessThan(zIndexes[1]);
  expect(zIndexes[1]).toBeLessThan(zIndexes[2]);
  await expect(page.locator(`${DRAWER}[data-overlay-top="true"]`)).toHaveCount(1);
  await expect(page.locator(DRAWER).nth(1)).toHaveAttribute("aria-hidden", "true");

  await page.keyboard.press("Escape");
  await expect(page.locator(DRAWER)).toHaveCount(2);
  await expect(page.getByTestId("open-third")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator(DRAWER)).toHaveCount(1);
  await expect(page.getByTestId("open-nested")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator(DRAWER)).toHaveCount(0);
  await expect(page.getByTestId("open-primary")).toBeFocused();
});

test("drawer backdrop dismisses only the top layer and panel clicks stay inside", async ({ page }) => {
  await openHarness(page, 1920, 1080);
  await openPrimary(page);
  await page.locator(TOP_DRAWER_PANEL).evaluate((panel) => panel.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  await expect(page.locator(DRAWER)).toHaveCount(1);

  await page.getByTestId("open-nested").click();
  await expect(page.locator(DRAWER)).toHaveCount(2);
  await page.locator(`${DRAWER}[data-overlay-top="true"]`).click({ position: { x: 4, y: 4 } });
  await expect(page.locator(DRAWER)).toHaveCount(1);
  await expect(page.getByTestId("open-nested")).toBeFocused();

  await page.getByTestId("open-nested").click();
  await page.getByTestId("open-third").click();
  await expect(page.locator(DRAWER)).toHaveCount(3);
  await page.locator(`${DRAWER}[data-overlay-top="true"]`).click({ position: { x: 4, y: 4 } });
  await expect(page.locator(DRAWER)).toHaveCount(2);
  await expect(page.getByTestId("open-third")).toBeFocused();
});

test("mixed modal stays above drawer and focus cannot escape", async ({ page }) => {
  await openHarness(page, 1440, 900);
  await openPrimary(page);
  await page.getByTestId("open-nested").click();
  await page.getByTestId("open-modal").click();
  const modal = page.locator('[data-overlay-kind="modal"]');
  await expect(modal).toHaveCount(1);
  await expect(modal).toHaveAttribute("data-overlay-top", "true");
  await modal.click({ position: { x: 4, y: 4 } });
  await expect(modal).toHaveCount(1);

  for (let index = 0; index < 8; index += 1) await page.keyboard.press("Tab");
  const focusInsideTop = await page.evaluate(() => Boolean(document.activeElement?.closest('[data-overlay-top="true"]')));
  expect(focusInsideTop).toBe(true);

  await page.keyboard.press("Escape");
  await expect(modal).toHaveCount(0);
  await expect(page.locator(DRAWER)).toHaveCount(2);
  await expect(page.getByTestId("open-modal")).toBeFocused();
});

test("mobile focus trap skips CSS-hidden drawer controls in both directions", async ({ page }) => {
  await openHarness(page, 390, 844);
  await openPrimary(page);
  const closeButton = page.getByRole("button", { name: "关闭" });
  const systemSummary = page.getByTestId("system-summary");
  const hiddenSizeToggle = page.locator(".project-drawer-size-toggle");
  await expect(hiddenSizeToggle).toBeHidden();

  await expect(page.locator(TOP_DRAWER_PANEL)).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(systemSummary).toBeFocused();

  await closeButton.focus();
  await page.keyboard.press("Shift+Tab");
  await expect(systemSummary).toBeFocused();

  await page.keyboard.press("Tab");
  await expect(closeButton).toBeFocused();
  await expect(hiddenSizeToggle).not.toBeFocused();
});

test("background is inert and scroll position is restored", async ({ page }) => {
  await openHarness(page, 1366, 768);
  await page.evaluate(() => window.scrollTo(0, 640));
  const before = await page.evaluate(() => window.scrollY);
  expect(before).toBeGreaterThan(600);
  await page.getByTestId("open-primary").evaluate((button: HTMLElement) => button.click());
  await expect(page.locator(TOP_DRAWER_PANEL)).toBeVisible();
  await expect(page.locator("#app")).toHaveAttribute("inert", "");
  expect(await page.evaluate(() => document.body.style.position)).toBe("fixed");
  await page.mouse.wheel(0, 900);
  await page.waitForTimeout(100);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect(await page.evaluate(() => document.body.style.top)).toBe(`${-before}px`);

  await page.getByRole("button", { name: "关闭" }).click();
  await expect(page.locator(DRAWER)).toHaveCount(0);
  await expect(page.locator("#app")).not.toHaveAttribute("inert", "");
  expect(await page.evaluate(() => window.scrollY)).toBe(before);
});

test("reduced motion keeps resizing operational", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openHarness(page, 1366, 768);
  await openPrimary(page);
  const handle = page.locator(".project-drawer-resize-handle");
  await handle.focus();
  const before = await panelBox(page);
  await handle.press("ArrowRight");
  await expect.poll(async () => (await panelBox(page)).width).toBeCloseTo(before.width - 24, 0);
});
