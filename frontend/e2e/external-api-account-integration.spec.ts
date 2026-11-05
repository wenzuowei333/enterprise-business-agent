import { expect, test, type Page, type Route } from "@playwright/test";

const generatedKey = "test_external_key_shown_once_123456";
const now = "2026-08-30T02:00:00Z";

const permissionFlags = {
  can_read_projects: true,
  can_read_customers: false,
  can_read_followups: false,
  can_read_judgements: false,
  can_read_tasks: false,
  can_read_approvals: false,
  can_read_audit_summary: false,
  can_read_products: false,
  can_read_suppliers: false,
  can_read_sales_summary: false,
  can_read_purchase_summary: false,
  can_read_inventory_summary: false,
  can_read_receivables: false,
  can_read_data_quality: false,
  can_read_changes: false,
  can_read_inventory_anomalies: false,
  can_read_inventory_evidence: false,
  can_read_sales_details_sensitive: false,
  can_read_purchase_details_sensitive: false,
  can_read_inventory_checks: false,
  can_read_imports: false,
  can_write_inventory_diagnoses: false,
  can_validate_inventory_actions: false,
  can_execute_inventory_rebuild: false,
  can_execute_inventory_upstream: false,
  can_read_inventory_action_status: false
};

function keyRow(id = "ext_test_1", name = "测试接入方") {
  return {
    id: id === "ext_test_1" ? 1 : 2,
    key_id: id,
    name,
    owner_name: "测试负责人",
    key_prefix: "ext_test",
    scope_region: null,
    scope_project_ids: [],
    allowed_customer_fields: ["customer_code", "customer_name"],
    allowed_ips: [],
    permissions: permissionFlags,
    permission_scopes: ["projects:read"],
    rate_limit_per_minute: 60,
    daily_request_limit: 10000,
    previous_key_prefix: null,
    previous_key_expires_at: null,
    rotated_at: null,
    rotation_count: 0,
    active: true,
    created_by_user_id: 1,
    created_at: now,
    updated_at: now,
    expires_at: null,
    last_used_at: now,
    last_used_ip: "127.0.0.1",
    revoked_at: null,
    revoked_reason: null
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockApplication(page: Page, permissions: string[]) {
  let rows = [keyRow()];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, { id: 31, username: "api-operator", real_name: "API 运维", role: "integration_operator", is_active: true, status: "active" });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, permissions);
      return;
    }
    if (url.pathname === "/api/v1/admin/stage1/summary") {
      await fulfillJson(route, { users: 1, employees: 0, roles: 1, permissions: permissions.length, authority_root_rules: 0, audit_logs: 1, import_batches: 0, customers: 0, products: 0, suppliers: 0 });
      return;
    }
    if (url.pathname === "/api/v1/external-api/catalog") {
      await fulfillJson(route, {
        base_url: "/api/external/v2",
        schema_version: "2.0",
        openapi_url: "/api/external/v2/openapi.json",
        customer_field_options: ["customer_code", "customer_name"],
        default_customer_fields: ["customer_code", "customer_name"],
        permission_options: [{ code: "can_read_projects", label: "读取项目" }],
        endpoints: [{ method: "GET", path: "/projects", permission: "can_read_projects", description: "读取授权项目" }]
      });
      return;
    }
    if (url.pathname === "/api/v1/external-api/keys" && request.method() === "GET") {
      await fulfillJson(route, rows);
      return;
    }
    if (url.pathname === "/api/v1/external-api/keys" && request.method() === "POST") {
      const created = keyRow("ext_test_2", "浏览器测试接入方");
      rows = [...rows, created];
      await fulfillJson(route, { api_key: generatedKey, key: created }, 201);
      return;
    }
    if (url.pathname.endsWith("/usage")) {
      await fulfillJson(route, { key_id: "ext_test_1", days: 7, total: 1, error_count: 0, items: [{ request_id: "req-test-1", endpoint: "/projects", method: "GET", status_code: 200, duration_ms: 18, response_count: 1, client_ip: "127.0.0.1", created_at: now }] });
      return;
    }
    if (/\/api\/v1\/external-api\/keys\/[^/]+\/(enable|disable|revoke)$/.test(url.pathname)) {
      const active = !url.pathname.endsWith("/disable") && !url.pathname.endsWith("/revoke");
      rows = rows.map((row) => row.key_id === "ext_test_1" ? { ...row, active, revoked_at: url.pathname.endsWith("/revoke") ? now : null } : row);
      await fulfillJson(route, rows[0]);
      return;
    }
    if (url.pathname === "/api/v1/admin/audit-logs") {
      await fulfillJson(route, [{ id: 1, user_id: 31, role_code: "integration_operator", action_type: "external_api_read", resource_type: "external_api", resource_id: "ext_test_1", ip_address: "127.0.0.1", created_at: now }]);
      return;
    }
    await fulfillJson(route, { detail: "not mocked" }, 404);
  });
}

async function openPath(page: Page, path: string) {
  await page.goto("index.html");
  await page.evaluate((nextPath) => {
    window.history.replaceState(null, "", nextPath);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
}

test("API 专职账号只看到账号管理中的外部 API 子页", async ({ page }) => {
  await mockApplication(page, ["external_api_key.view"]);
  await openPath(page, "/users/external-api");

  await expect(page).toHaveURL(/\/users\/external-api$/);
  await expect(page.getByRole("heading", { name: "账号管理" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "外部 API 接入" })).toBeVisible();
  await expect(page.getByRole("button", { name: "外部 API", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "账号列表", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "新增 Key", exact: true })).toHaveCount(0);
  await expect(page.getByText("测试接入方", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "停用", exact: true })).toHaveCount(0);
});

test("旧 CRM 地址迁移到账号管理并保留查询参数", async ({ page }) => {
  await mockApplication(page, ["external_api_key.view"]);
  await openPath(page, "/crm/api-access?source=bookmark");

  await expect(page).toHaveURL(/\/users\/external-api\?source=bookmark$/);
  await expect(page.getByRole("heading", { name: "外部 API 接入" })).toBeVisible();
  await expect(page.getByText("接口开放", { exact: true })).toHaveCount(0);
});

test("完整权限支持一次性 Key、用量和生命周期操作", async ({ page }) => {
  await mockApplication(page, ["external_api_key.view", "external_api_key.create", "external_api_key.revoke", "audit.view"]);
  await openPath(page, "/users/external-api");

  await page.getByRole("button", { name: "新增 Key", exact: true }).first().click();
  const drawer = page.locator('[data-overlay-kind="drawer"][data-overlay-top="true"]');
  await expect(drawer.getByRole("heading", { name: "新增外部 API Key" })).toBeVisible();
  await drawer.getByPlaceholder("例如：外部分析智能体").fill("浏览器测试接入方");
  await drawer.getByRole("button", { name: "生成 API Key", exact: true }).click();
  await expect(drawer.getByText(generatedKey, { exact: true })).toBeVisible();
  await drawer.getByRole("button", { name: "完成", exact: true }).click();
  await expect(page.getByText(generatedKey, { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "用量", exact: true }).first().click();
  await expect(page.getByText("Key 调用明细", { exact: true })).toBeVisible();
  await expect(page.getByText("18 ms", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "停用", exact: true }).first().click();
  await expect(page.getByText("停用", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "审计日志", exact: true }).first().click();
  await expect(page).toHaveURL(/\/users\/audit$/);
});

test("无外部 API 权限时直达地址回退到首个有权账号子页", async ({ page }) => {
  await mockApplication(page, ["user.view"]);
  await openPath(page, "/users/external-api");

  await expect(page).toHaveURL(/\/users$/);
  await expect(page.getByText("账号列表", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "外部 API", exact: true })).toHaveCount(0);
});

test("外部 API 页面在窄屏内保持横向内容受控", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApplication(page, ["external_api_key.view"]);
  await openPath(page, "/users/external-api");

  const width = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
  expect(width.scroll - width.client).toBeLessThanOrEqual(1);
  await expect(page.getByRole("heading", { name: "外部 API 接入" })).toBeVisible();
});
