import { expect, test, type Route } from "@playwright/test";

const now = "2026-08-01T02:00:00Z";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body)
  });
}

test("new CRM lead submits detailed address and customer group", async ({ page }) => {
  let createdLead: Record<string, unknown> | null = null;
  let submittedPayload: Record<string, unknown> | null = null;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, {
        id: 7,
        username: "sales-test",
        real_name: "测试销售",
        employee_code: "E007",
        role: "salesperson",
        is_active: true,
        status: "active"
      });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, ["crm_lead.view", "crm_lead.create", "crm_lead.edit"]);
      return;
    }
    if (url.pathname === "/api/v1/admin/stage1/summary") {
      await fulfillJson(route, {
        users: 0,
        employees: 0,
        roles: 0,
        permissions: 0,
        authority_root_rules: 0,
        audit_logs: 0,
        import_batches: 0,
        customers: 0,
        products: 0,
        suppliers: 0
      });
      return;
    }
    if (url.pathname === "/api/v1/crm/leads/duplicate-check") {
      await fulfillJson(route, {
        has_blocking_duplicates: false,
        requires_acknowledgement: false,
        has_hidden_duplicates: false,
        items: []
      });
      return;
    }
    if (url.pathname === "/api/v1/crm/leads" && request.method() === "POST") {
      submittedPayload = request.postDataJSON() as Record<string, unknown>;
      createdLead = {
        ...submittedPayload,
        id: 88,
        lead_no: "LEAD-88",
        status: "draft",
        priority: "normal",
        pool_status: "private",
        current_approval_id: null,
        created_at: now,
        updated_at: now,
        product_intents: [],
        followups: [],
        assignments: []
      };
      await fulfillJson(route, createdLead, 201);
      return;
    }
    if (url.pathname === "/api/v1/crm/leads" && request.method() === "GET") {
      const items = createdLead ? [createdLead] : [];
      await fulfillJson(route, {
        items,
        total: items.length,
        limit: 24,
        offset: 0,
        summary: { total: items.length, by_status: createdLead ? { draft: 1 } : {} }
      });
      return;
    }
    if (url.pathname === "/api/v1/crm/leads/88") {
      await fulfillJson(route, createdLead);
      return;
    }
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "not mocked" })
    });
  });

  await page.goto("index.html");
  await page.evaluate(() => {
    window.history.replaceState(null, "", "/crm/leads");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.getByRole("heading", { name: "客户开发" })).toBeVisible();
  await page.getByRole("button", { name: "新建线索" }).click();

  const dialog = page.getByRole("dialog", { name: "新建客户线索" });
  await dialog.getByLabel("线索名称").fill("上海恒溯客户线索");
  await dialog.getByLabel("客户公司").fill("上海恒溯饰品商行");
  await dialog.getByLabel("详细地址").fill("上海市九州星寓28栋114室");
  await dialog.getByLabel("客户群名称").fill("恒溯饰品合作群");
  await dialog.getByRole("button", { name: "检查重复并保存" }).click();

  await expect.poll(() => submittedPayload).toMatchObject({
    lead_name: "上海恒溯客户线索",
    company_name: "上海恒溯饰品商行",
    address: "上海市九州星寓28栋114室",
    customer_group_name: "恒溯饰品合作群"
  });
  await expect(page.getByRole("dialog", { name: "上海恒溯饰品商行" })).toContainText("详细地址：上海市九州星寓28栋114室");
  await expect(page.getByRole("dialog", { name: "上海恒溯饰品商行" })).toContainText("客户群：恒溯饰品合作群");
});
