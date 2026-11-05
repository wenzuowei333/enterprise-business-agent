import { expect, test, type Page, type Route } from "@playwright/test";

type LeadRow = {
  id: number;
  lead_no: string;
  lead_name: string;
  company_name: string;
  contact_name: string;
  contact_phone: string;
  source: string;
  region: string;
  business_line: string;
  intent_summary: string;
  status: string;
  priority: string;
  pool_status: string;
  assigned_user_id: number;
  current_approval_id: number | null;
  next_followup_at: string | null;
  created_at: string;
  updated_at: string;
  product_intents: unknown[];
  followups: unknown[];
  assignments: unknown[];
};

const now = "2026-07-27T08:00:00Z";

function lead(id: number, companyName: string, status: string): LeadRow {
  return {
    id,
    lead_no: `LEAD-${id}`,
    lead_name: `${companyName}线索`,
    company_name: companyName,
    contact_name: "张经理",
    contact_phone: `1380000000${id}`,
    source: "转介绍",
    region: "华南",
    business_line: "企业服务",
    intent_summary: "需要进一步核实合作方案",
    status,
    priority: "normal",
    pool_status: "private",
    assigned_user_id: 7,
    current_approval_id: null,
    next_followup_at: null,
    created_at: now,
    updated_at: now,
    product_intents: [],
    followups: [],
    assignments: []
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body)
  });
}

async function openLead(page: Page, companyName: string) {
  await page.getByRole("button", { name: new RegExp(companyName) }).click();
  const dialog = page.getByRole("dialog", { name: companyName });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("推进阶段")).toBeVisible();
  return dialog;
}

test("lead stage supports direct qualification, closed reactivation, and keeps approval states locked", async ({ page }) => {
  const leads = [
    lead(1, "待接触测试客户", "draft"),
    lead(2, "已关闭测试客户", "closed"),
    lead(3, "审批中测试客户", "conversion_pending")
  ];
  const patches: Array<{ leadId: number; body: Record<string, unknown> }> = [];

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
      await fulfillJson(route, ["crm_lead.view", "crm_lead.edit"]);
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
    if (url.pathname === "/api/v1/crm/leads" && request.method() === "GET") {
      await fulfillJson(route, { items: leads, total: leads.length, limit: 24, offset: 0 });
      return;
    }

    const leadMatch = url.pathname.match(/^\/api\/v1\/crm\/leads\/(\d+)$/);
    if (leadMatch) {
      const leadId = Number(leadMatch[1]);
      const current = leads.find((item) => item.id === leadId);
      if (!current) {
        await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "lead not found" }) });
        return;
      }
      if (request.method() === "PATCH") {
        const body = request.postDataJSON() as Record<string, unknown>;
        patches.push({ leadId, body });
        Object.assign(current, body, { updated_at: "2026-07-27T09:00:00Z" });
      }
      await fulfillJson(route, current);
      return;
    }

    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "not mocked" }) });
  });

  await page.goto("index.html");
  await page.evaluate(() => {
    window.history.replaceState(null, "", "/crm/leads");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.getByRole("heading", { name: "客户开发" })).toBeVisible();

  const draftDialog = await openLead(page, "待接触测试客户");
  const draftStatus = draftDialog.getByLabel("推进阶段");
  await expect(draftStatus.locator('option[value="qualified"]')).toHaveText("已确认意向");
  await draftStatus.selectOption("qualified");

  await expect.poll(() => patches.filter((item) => item.leadId === 1)).toEqual([
    { leadId: 1, body: { status: "qualified" } }
  ]);
  await expect(draftStatus).toHaveValue("qualified");
  await expect(draftDialog.getByText("已确认意向", { exact: true }).first()).toBeVisible();
  await expect(draftDialog.getByText("已更新客户开发阶段。", { exact: true })).toBeVisible();

  await draftDialog.getByRole("button", { name: "关闭" }).click();
  await expect(draftDialog).toHaveCount(0);

  const closedDialog = await openLead(page, "已关闭测试客户");
  const closedStatus = closedDialog.getByLabel("推进阶段");
  await expect(closedStatus).toBeEnabled();
  await expect(closedStatus.locator('option[value="active"]')).toHaveText("推进中");
  await closedStatus.selectOption("active");

  await expect.poll(() => patches.filter((item) => item.leadId === 2)).toEqual([
    { leadId: 2, body: { status: "active" } }
  ]);
  await expect(closedStatus).toHaveValue("active");
  await expect(closedDialog.getByText("推进中", { exact: true }).first()).toBeVisible();
  await expect(closedDialog.getByText("已更新客户开发阶段。", { exact: true })).toBeVisible();

  await closedDialog.getByRole("button", { name: "关闭" }).click();
  await expect(closedDialog).toHaveCount(0);

  const pendingDialog = await openLead(page, "审批中测试客户");
  await expect(pendingDialog.getByLabel("推进阶段")).toBeDisabled();
  expect(patches).toHaveLength(2);
});
