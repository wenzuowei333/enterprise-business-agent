import { defineConfig } from "@playwright/test";

const isCi = Boolean(process.env.CI);
const browserChannel = process.env.PW_BROWSER_CHANNEL || (isCi ? undefined : "chrome");
const testPort = Number(process.env.PW_PORT || 4173);

export default defineConfig({
  testDir: "./e2e",
  testMatch: "*.spec.ts",
  timeout: 45_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: isCi,
  retries: isCi ? 1 : 0,
  outputDir: "test-results",
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }]
  ],
  use: {
    baseURL: `http://127.0.0.1:${testPort}/static/react/`,
    browserName: "chromium",
    channel: browserChannel,
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure"
  },
  webServer: {
    command: `npx vite --host 127.0.0.1 --port ${testPort} --strictPort`,
    // Pre-transform the oversized application module before per-test timeouts start.
    url: `http://127.0.0.1:${testPort}/static/react/src/App.tsx`,
    env: { VITE_EXCEPTION_CENTER_ENABLED: "true" },
    reuseExistingServer: false,
    timeout: 120_000
  }
});
