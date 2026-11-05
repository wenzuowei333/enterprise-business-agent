import { expect, test, type Route } from "@playwright/test";

type LeadRow = {
  id: number;
  lead_no: string;
  lead_name: string;
  company_name: string;
  status: string;
  contact_name: string;
  contact_phone: string;
  source: string;
  region: string;
  business_line: string;
  intent_summary: string;
  next_followup_at: string | null;
};

const leadRows: LeadRow[] = [
  {
    id: 1,
    lead_no: "LEAD-DRAFT",
    lead_name: "待接触线索",
    company_name: "待接触客户",
    status: "draft",
    contact_name: "张经理",
    contact_phone: "00000000000",
    source: "展会",
    region: "华东",
    business_line: "包装",
    intent_summary: "首次接触",
    next_followup_at: null
  },
  {
    id: 2,
    lead_no: "LEAD-ACTIVE",
    lead_name: "推进中线索",
    company_name: "推进中客户",
    status: "active",
    contact_name: "李经理",
    contact_phone: "00000000000",
    source: "转介绍",
    region: "华南",
    business_line: "礼品",
    intent_summary: "方案沟通",
    next_followup_at: "2026-07-28T09:00:00Z"
  },
  {
    id: 3,
    lead_no: "LEAD-QUALIFIED",
    lead_name: "已确认线索",
    company_name: "已确认客户",
    status: "qualified",
    contact_name: "王经理",
    contact_phone: "00000000000",
    source: "官网",
    region: "华北",
    business_line: "定制",
    intent_summary: "已确认合作意向",
    next_followup_at: null
  },
  {
    id: 4,
    lead_no: "LEAD-CONVERSION",
    lead_name: "转正审批线索",
    company_name: "转正审批客户",
    status: "conversion_pending",
    contact_name: "赵经理",
    contact_phone: "00000000000",
    source: "拜访",
    region: "华中",
    business_line: "供应链",
    intent_summary: "等待转正审批",
    next_followup_at: null
  }
];

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body)
  });
}

test("lead metric cards filter the real lead pool and toggle off", async ({ page }) => {
  const leadRequests: URL[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
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
      await fulfillJson(route, ["crm_lead.view"]);
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
    if (url.pathname === "/api/v1/crm/leads") {
      leadRequests.push(url);
      const statusGroup = url.searchParams.get("status_group");
      const statusValue = url.searchParams.get("status_value");
      const items = statusGroup === "followup_pending"
        ? leadRows.filter((row) => row.status === "draft" || row.status === "active")
        : statusValue
          ? leadRows.filter((row) => row.status === statusValue)
          : leadRows;
      await fulfillJson(route, {
        items,
        total: items.length,
        limit: 24,
        offset: 0,
        summary: {
          total: 156,
          by_status: { draft: 95, active: 61, qualified: 0, conversion_pending: 0, converted: 0 }
        }
      });
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
  await expect(page.getByText("已确认客户", { exact: true })).toBeVisible();

  const pendingMetric = page.locator('button[aria-pressed]').filter({ hasText: "待跟进" });
  await expect(pendingMetric).toContainText("156");
  await expect(pendingMetric).toContainText("待接触 95 · 推进中 61");
  await pendingMetric.click();

  await expect(pendingMetric).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("阶段")).toHaveValue("followup_pending");
  await expect.poll(() => leadRequests.at(-1)?.searchParams.get("status_group")).toBe("followup_pending");
  await expect.poll(() => leadRequests.at(-1)?.searchParams.get("status_value")).toBeNull();
  await expect(page.getByText("待接触客户", { exact: true })).toBeVisible();
  await expect(page.getByText("推进中客户", { exact: true })).toBeVisible();
  await expect(page.getByText("已确认客户", { exact: true })).toHaveCount(0);
  await expect(pendingMetric).toContainText("156");

  await pendingMetric.click();

  await expect(pendingMetric).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByLabel("阶段")).toHaveValue("");
  await expect.poll(() => leadRequests.at(-1)?.searchParams.get("status_group")).toBeNull();
  await expect(page.getByText("已确认客户", { exact: true })).toBeVisible();
});
