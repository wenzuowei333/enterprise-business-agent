import { expect, test, type Route } from "@playwright/test";

const caseNo = "EXC-20260728-TESTCASE0001";
const detectedAt = "2026-07-28T02:30:00Z";

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body)
  });
}

const summary = {
  total: 1,
  open: 1,
  action_required: 0,
  processing: 0,
  blocked: 0,
  resolved: 0,
  ignored: 0,
  unread_notifications: 1,
  ai_enabled: false,
  actions_enabled: false,
  by_domain: { inventory: 1 },
  by_severity: { critical: 1 },
  by_occurrence: { new: 1 }
};

const caseItem = {
  id: 1,
  case_no: caseNo,
  domain: "inventory",
  rule_code: "inventory.negative_stock",
  title: "库存数量异常",
  severity: "critical",
  status: "open",
  occurrence_type: "new",
  resource_type: "inventory_snapshot",
  resource_id: "17",
  resource_code: "P-0017",
  resource_name: "测试商品",
  source_type: "inventory_snapshot_quality",
  source_id: "17",
  source_batch_kind: "import",
  source_batch_id: 91,
  data_date: "2026-07-27",
  evidence_version: "evidence-v2",
  reason: "库存结存为负数",
  initial_guidance: "核对上游单据后重新同步。",
  action_path: "/inventory?attention_state=needs_attention&product_code=P-0017",
  affected_rows: 1,
  affected_quantity: "-12",
  assignee_user_id: 9,
  assignee_name: "数据专员",
  due_at: "2026-07-29T02:30:00Z",
  detected_at: detectedAt,
  last_seen_at: detectedAt,
  metadata: {},
  diagnosis: {
    id: 701,
    evidence_version: "evidence-v1",
    summary: "旧证据诊断不应显示"
  }
};

test("exception center keeps current evidence and mobile content contained", async ({ page }) => {
  let notificationAcknowledged = false;
  let feedbackPayload: Record<string, unknown> | null = null;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, {
        id: 5,
        username: "exception-viewer",
        real_name: "异常查看员",
        role: "data_operator",
        is_active: true,
        status: "active"
      });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, [
        "exception_center.view",
        "exception_center.diagnose",
        "exception_center.action_execute",
        "inventory_snapshot.view",
        "inventory_check.upload"
      ]);
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
    if (url.pathname === "/api/v1/exceptions/summary") {
      await fulfillJson(route, summary);
      return;
    }
    if (url.pathname === "/api/v1/exception-notifications") {
      await fulfillJson(route, [{
        id: 81,
        case_no: caseNo,
        notification_type: "high_risk",
        title: "库存异常通知",
        message: "测试商品库存为负数",
        is_read: false,
        read_at: null,
        acknowledged_at: notificationAcknowledged ? detectedAt : null,
        created_at: detectedAt
      }]);
      return;
    }
    if (url.pathname === "/api/v1/exception-notifications/81/acknowledge") {
      notificationAcknowledged = true;
      await fulfillJson(route, {
        id: 81,
        case_no: caseNo,
        notification_type: "high_risk",
        title: "库存异常通知",
        message: "测试商品库存为负数",
        is_read: true,
        read_at: detectedAt,
        acknowledged_at: detectedAt,
        created_at: detectedAt
      });
      return;
    }
    if (url.pathname === "/api/v1/exceptions/page") {
      await fulfillJson(route, { items: [caseItem], total: 1, limit: 30, offset: 0 });
      return;
    }
    if (url.pathname === `/api/v1/exceptions/${caseNo}`) {
      await fulfillJson(route, {
        ...caseItem,
        evidence: { stock_qty: -12, product_code: "P-0017", batch_id: 91, warehouse_name: null, unit: null },
        diagnoses: [
          { id: 701, evidence_version: "evidence-v1", summary: "旧证据诊断不应显示" },
          { id: 702, evidence_version: "evidence-v2", summary: "当前证据诊断" }
        ],
        actions: [],
        events: []
      });
      return;
    }
    if (url.pathname === "/api/v1/exception-diagnoses/702/feedback") {
      const payload = route.request().postDataJSON();
      feedbackPayload = payload;
      await fulfillJson(route, {
        id: 702,
        evidence_version: "evidence-v2",
        summary: "当前证据诊断",
        feedback_rating: payload.rating,
        feedback_note: payload.note,
        feedback_by_user_id: 5,
        feedback_at: detectedAt
      });
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
    window.history.replaceState(null, "", "/exceptions");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  await expect(page.getByRole("heading", { name: "统一异常中心" })).toBeVisible();
  await page.getByTitle("通知").click();
  await page.getByRole("button", { name: "确认已知晓：库存异常通知" }).click();
  await expect.poll(() => notificationAcknowledged).toBe(true);
  await expect(page.getByRole("button", { name: "确认已知晓：库存异常通知" })).toHaveCount(0);
  await page.getByTitle("通知").click();
  await expect(page.getByText("数据专员", { exact: false })).toBeVisible();
  await page.getByText("库存数量异常", { exact: true }).click();

  const drawer = page.locator('[data-overlay-kind="drawer"][data-overlay-top="true"]');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("当前证据诊断", { exact: true })).toBeVisible();
  await expect(drawer.getByText("旧证据诊断不应显示", { exact: true })).toHaveCount(0);
  await expect(drawer.locator('[data-evidence-missing="true"]').filter({ hasText: "仓库未提供" })).toBeVisible();
  await expect(drawer.locator('[data-evidence-missing="true"]').filter({ hasText: "计量单位未提供" })).toBeVisible();
  await expect(drawer.getByRole("button", { name: "定位原始记录" })).toBeVisible();
  await expect(drawer.getByTestId("exception-diagnose")).toHaveCount(0);
  await expect(drawer.getByTestId("exception-actions")).toHaveCount(0);
  await drawer.getByRole("button", { name: "部分正确" }).click();
  await expect(drawer.getByRole("button", { name: "保存反馈" })).toBeDisabled();
  await drawer.getByLabel("问题分类（必选）").selectOption("insufficient_evidence");
  await expect(drawer.getByRole("button", { name: "保存反馈" })).toBeDisabled();
  await drawer.getByLabel("具体原因（必填）").fill("仍需核对上游日期");
  await drawer.getByRole("button", { name: "保存反馈" }).click();
  await expect.poll(() => feedbackPayload).toEqual({
    rating: "partial",
    note: "[问题分类：证据不足]\n仍需核对上游日期"
  });
  await expect(drawer.getByTestId("exception-feedback-saved")).toContainText("部分正确");
  await expect(drawer.getByLabel("问题分类（必选）")).toHaveValue("insufficient_evidence");
  await expect(drawer.getByLabel("具体原因（必填）")).toHaveValue("仍需核对上游日期");

  const feedbackPrefix = "[问题分类：证据不足]\n";
  const explanationLimit = 2000 - feedbackPrefix.length;
  const feedbackReason = drawer.getByLabel("具体原因（必填）");
  await feedbackReason.fill("测".repeat(2000));
  await expect.poll(async () => (await feedbackReason.inputValue()).length).toBe(explanationLimit);
  feedbackPayload = null;
  await drawer.getByRole("button", { name: "更新反馈" }).click();
  await expect.poll(() => {
    const note = feedbackPayload && typeof feedbackPayload.note === "string" ? feedbackPayload.note : "";
    return { length: note.length, hasPrefix: note.startsWith(feedbackPrefix) };
  }).toEqual({ length: 2000, hasPrefix: true });

  const panelBox = await drawer.locator(".project-drawer-panel").boundingBox();
  expect(panelBox).not.toBeNull();
  expect(Math.abs(panelBox!.width - 390)).toBeLessThanOrEqual(1);
  const containment = await drawer.locator(".project-drawer-body").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth
  }));
  expect(containment.scrollWidth - containment.clientWidth).toBeLessThanOrEqual(1);
});

test("exception metrics, occurrence filters, and current-page batch actions stay in sync", async ({ page }) => {
  const secondCaseNo = "EXC-20260728-TESTCASE0002";
  const processingCaseNo = "EXC-20260728-TESTCASE0003";
  const resolvedCaseNo = "EXC-20260728-TESTCASE0004";
  const pageQueries: Array<Record<string, string>> = [];
  const summaryQueries: Array<Record<string, string>> = [];
  const batchAssignPayloads: Array<Record<string, unknown>> = [];
  let batchIgnorePayload: Record<string, unknown> | null = null;
  const items = [
    caseItem,
    {
      ...caseItem,
      id: 2,
      case_no: secondCaseNo,
      resource_id: "18",
      resource_code: "P-0018",
      resource_name: "第二个测试商品",
      diagnosis: null
    },
    {
      ...caseItem,
      id: 3,
      case_no: processingCaseNo,
      status: "processing",
      resource_id: "19",
      resource_code: "P-0019",
      resource_name: "处理中测试商品",
      diagnosis: null
    },
    {
      ...caseItem,
      id: 4,
      case_no: resolvedCaseNo,
      status: "resolved",
      resource_id: "20",
      resource_code: "P-0020",
      resource_name: "已解决测试商品",
      diagnosis: null
    }
  ];

  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, {
        id: 8,
        username: "exception-manager",
        real_name: "异常管理员",
        role: "admin",
        is_active: true,
        status: "active"
      });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, [
        "exception_center.view",
        "exception_center.diagnose",
        "exception_center.manage",
        "inventory_snapshot.view",
        "user.view"
      ]);
      return;
    }
    if (url.pathname === "/api/v1/admin/stage1/summary") {
      await fulfillJson(route, {
        users: 1,
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
    if (url.pathname === "/api/v1/exception-notifications") {
      await fulfillJson(route, []);
      return;
    }
    if (url.pathname === "/api/v1/exceptions/summary") {
      summaryQueries.push(Object.fromEntries(url.searchParams));
      await fulfillJson(route, {
        ...summary,
        total: 4,
        open: 2,
        processing: 1,
        resolved: 1,
        unread_notifications: 0,
        by_occurrence: url.searchParams.get("occurrence_type") === "new" ? { new: 4 } : { baseline: 0, new: 4, reopened: 0 }
      });
      return;
    }
    if (url.pathname === "/api/v1/exceptions/page") {
      pageQueries.push(Object.fromEntries(url.searchParams));
      await fulfillJson(route, { items, total: 4, limit: 30, offset: 0 });
      return;
    }
    if (url.pathname === "/api/v1/users") {
      await fulfillJson(route, [{ id: 12, username: "data-owner", real_name: "数据负责人", role: "data_operator", is_active: true, status: "active" }]);
      return;
    }
    if (url.pathname === "/api/v1/exceptions/batch/assign") {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      batchAssignPayloads.push(payload);
      await fulfillJson(route, { updated_count: (payload.case_nos as string[]).length, items });
      return;
    }
    if (url.pathname === "/api/v1/exceptions/batch/ignore") {
      batchIgnorePayload = route.request().postDataJSON();
      await fulfillJson(route, { updated_count: 2, items: items.map((item) => ({ ...item, status: "ignored" })) });
      return;
    }
    await fulfillJson(route, {});
  });

  await page.goto("index.html");
  await page.evaluate(() => {
    window.history.replaceState(null, "", "/exceptions");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  await expect(page.getByRole("heading", { name: "统一异常中心" })).toBeVisible();
  await page.getByTestId("exception-summary-open").click();
  await expect.poll(() => new URL(page.url()).searchParams.get("status")).toBe("open");
  await expect.poll(() => pageQueries.some((query) => query.status === "open")).toBe(true);

  await page.getByLabel("发生类型").selectOption("new");
  await expect.poll(() => new URL(page.url()).searchParams.get("occurrence_type")).toBe("new");
  await expect.poll(() => pageQueries.some((query) => query.status === "open" && query.occurrence_type === "new")).toBe(true);
  await expect.poll(() => summaryQueries.some((query) => query.occurrence_type === "new")).toBe(true);
  await expect(page.getByTestId("exception-occurrence-help")).toContainText("复发");
  await page.getByTestId("exception-summary-all").click();
  await expect.poll(() => new URL(page.url()).searchParams.get("status")).toBeNull();
  await expect.poll(() => pageQueries.some((query) => query.occurrence_type === "new" && query.status === undefined)).toBe(true);

  const selectCurrentPage = page.getByLabel("选择当前页全部案件");
  await expect(selectCurrentPage).toBeVisible();
  await selectCurrentPage.check();
  await expect(page.getByTestId("exception-batch-toolbar")).toContainText("已选 3 条");
  await expect(page.getByLabel(`选择案件 ${resolvedCaseNo}`)).toHaveCount(0);
  await expect(page.getByTestId("exception-batch-ignore-blocked")).toContainText("1 条处理中案件");
  await expect(page.getByRole("button", { name: "批量忽略" })).toBeDisabled();
  await page.getByTestId("exception-batch-assignee").selectOption("12");
  await page.getByTestId("exception-batch-due-at").fill("2026-07-31T09:30");
  await page.getByRole("button", { name: "应用更新" }).click();
  await expect(page.getByTestId("exception-batch-success")).toContainText("已更新 3 条");
  expect(batchAssignPayloads[0]).toEqual(expect.objectContaining({ case_nos: [caseNo, secondCaseNo, processingCaseNo], assignee_user_id: 12 }));
  expect(batchAssignPayloads[0]).toEqual(expect.objectContaining({ due_at: expect.any(String) }));

  await expect(selectCurrentPage).toBeVisible();
  await expect(selectCurrentPage).not.toBeChecked();
  await selectCurrentPage.check();
  await page.getByTestId("exception-batch-assignee").selectOption({ label: "恢复默认自动分派" });
  await page.getByTestId("exception-batch-recalculate-due").check();
  await page.getByRole("button", { name: "应用更新" }).click();
  await expect.poll(() => batchAssignPayloads.length).toBe(2);
  expect(batchAssignPayloads[1]).toEqual({ case_nos: [caseNo, secondCaseNo, processingCaseNo], assignee_user_id: null, due_at: null });

  await expect(selectCurrentPage).toBeVisible();
  await expect(selectCurrentPage).not.toBeChecked();
  await selectCurrentPage.check();
  await page.getByLabel(`选择案件 ${processingCaseNo}`).uncheck();
  await expect(page.getByTestId("exception-batch-ignore-blocked")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "批量忽略" })).toBeEnabled();
  await page.getByRole("button", { name: "批量忽略" }).click();
  await page.getByTestId("exception-batch-ignore-reason").fill("测试期间暂不处理");
  await page.getByTestId("exception-batch-ignore-until").fill("2026-08-02T10:00");
  await page.getByRole("button", { name: "确认批量忽略" }).click();
  await expect(page.getByTestId("exception-batch-success")).toContainText("已忽略 2 条");
  expect(batchIgnorePayload).toEqual(expect.objectContaining({ case_nos: [caseNo, secondCaseNo], reason: "测试期间暂不处理", ignored_until: expect.any(String) }));
});

test("phase-three filters, aggregation, evidence, active jobs, verification, and source return stay connected", async ({ page }) => {
  const pageQueries: Array<Record<string, string>> = [];
  const aggregationQueries: Array<Record<string, string>> = [];
  let activeJobPolls = 0;
  let verifyPayload: Record<string, unknown> | null = null;
  let verified = false;
  let detailFetches = 0;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, { id: 9, username: "exception-owner", real_name: "异常负责人", role: "data_operator", is_active: true, status: "active" });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, ["exception_center.view", "exception_center.diagnose", "exception_center.manage", "inventory_snapshot.view"]);
      return;
    }
    if (url.pathname === "/api/v1/admin/stage1/summary") {
      await fulfillJson(route, { users: 0, employees: 0, roles: 0, permissions: 0, authority_root_rules: 0, audit_logs: 0, import_batches: 0, customers: 0, products: 0, suppliers: 0 });
      return;
    }
    if (url.pathname === "/api/v1/exception-notifications") {
      await fulfillJson(route, []);
      return;
    }
    if (url.pathname === "/api/v1/exceptions/summary") {
      await fulfillJson(route, {
        ...summary,
        ai_enabled: true,
        actions_enabled: false,
        manual_ai_enabled: true,
        scheduled_ai_enabled: false,
        full_scan_enabled: true,
        digest_enabled: true,
        assigned_to_me: 1,
        unassigned: 2,
        overdue: 1,
        due_soon: 3
      });
      return;
    }
    if (url.pathname === "/api/v1/exceptions/aggregations") {
      aggregationQueries.push(Object.fromEntries(url.searchParams));
      const groupBy = url.searchParams.get("group_by") ?? "rule";
      await fulfillJson(route, groupBy === "batch"
        ? {
            group_by: "batch",
            groups: [
              { key: "unassigned", label: "未关联批次", source_batch_kind: null, source_batch_id: null, count: 1, critical: 1, high: 0, warning: 0, overdue: 1 },
              { key: "import:91", label: "导入批次 91", source_batch_kind: "import", source_batch_id: 91, count: 2, critical: 0, high: 2, warning: 0, overdue: 0 },
              { key: "inventory_check:91", label: "库存核验批次 91", source_batch_kind: "inventory_check", source_batch_id: 91, count: 3, critical: 0, high: 1, warning: 2, overdue: 0 }
            ],
            total: 205,
            truncated: true
          }
        : { group_by: "rule", groups: [{ key: "inventory.negative_stock", label: "库存负数", count: 1, critical: 1, high: 0, warning: 0, overdue: 1 }], total: 1, truncated: false });
      return;
    }
    if (url.pathname === "/api/v1/exceptions/page") {
      pageQueries.push(Object.fromEntries(url.searchParams));
      await fulfillJson(route, { items: [{ ...caseItem, is_mine: true, sla_status: "overdue" }], total: 1, limit: 30, offset: 0 });
      return;
    }
    if (url.pathname === `/api/v1/exceptions/${caseNo}` && route.request().method() === "GET") {
      detailFetches += 1;
      await fulfillJson(route, {
        ...caseItem,
        status: verified ? "resolved" : "open",
        evidence_version: verified ? "evidence-v3" : "evidence-v2",
        is_mine: true,
        sla_status: "overdue",
        processing_kind: verified ? null : "manual_diagnosis",
        evidence: verified ? {
          product_code: "P-0017",
          product_name: "复检后测试商品",
          warehouse_name: "一号仓",
          opening_qty: 10,
          purchase_qty: 14,
          sales_qty: 24,
          calculated_closing: 0,
          stock_qty: 0,
          difference_qty: 0,
          batch_id: 92,
          data_date: "2026-07-28"
        } : {
          product_code: "P-0017",
          product_name: "测试商品",
          warehouse_name: "一号仓",
          opening_qty: 10,
          purchase_qty: 2,
          sales_qty: 24,
          calculated_closing: -12,
          stock_qty: -12,
          difference_qty: 0,
          batch_id: 91,
          data_date: "2026-07-27"
        },
        diagnosis: verified ? null : {
          id: 702,
          evidence_version: "evidence-v2",
          root_cause_code: "missing_purchase",
          summary: "采购单据未进入当前有效批次。",
          confidence: 0.97,
          disposition: "manual_review",
          evidence_refs: ["batch:91", "product:P-0017"],
          impact: { summary: "库存结存少计 12 件" },
          recommended_steps: ["核对采购单据", "重新同步库存快照"],
          missing_evidence: ["上游采购单状态"]
        },
        diagnoses: [],
        actions: [],
        events: [],
        active_diagnosis_job: verified ? null : {
          id: 801,
          job_no: "DJ-801",
          case_no: caseNo,
          evidence_version: "evidence-v2",
          trigger_type: "manual",
          status: "queued",
          reused: false,
          attempts: 0,
          created_at: detectedAt
        }
      });
      return;
    }
    if (url.pathname === "/api/v1/exception-jobs/801") {
      activeJobPolls += 1;
      await fulfillJson(route, { id: 801, job_no: "DJ-801", case_no: caseNo, evidence_version: "evidence-v2", trigger_type: "manual", status: "queued", reused: false, attempts: 0, created_at: detectedAt });
      return;
    }
    if (url.pathname === `/api/v1/exceptions/${caseNo}/verify`) {
      verifyPayload = route.request().postDataJSON();
      verified = true;
      await fulfillJson(route, {
        case: { ...caseItem, status: "resolved", verified_at: detectedAt },
        resolved: true,
        before: { status: "open", evidence_version: "evidence-v2", affected_rows: 1, affected_quantity: -12, summary: "库存仍为负数" },
        after: { status: "resolved", evidence_version: "evidence-v3", affected_rows: 0, affected_quantity: 0, summary: "最新扫描未再发现负库存" },
        note: "已核对采购单并重新同步",
        evidence_changed: true,
        scan_result: { created: 0, updated: 1, resolved: 1 }
      });
      return;
    }
    if (url.pathname === "/api/v1/process-data/inventory-snapshots/page") {
      await fulfillJson(route, { items: [], total: 0, limit: 50, offset: 0, summary: null, attention_summary: null });
      return;
    }
    if (url.pathname === "/api/v1/process-data/inventory-snapshots/hierarchy/tree") {
      await fulfillJson(route, { id: "inventory_snapshot:root", label: "全部库存", path: [], count: 0, abnormal_count: 0, children: [] });
      return;
    }
    await fulfillJson(route, {});
  });

  await page.goto("index.html");
  await page.evaluate(() => {
    window.history.replaceState(null, "", "/exceptions?source_batch_kind=import&source_batch_id=91&source_batch_unassigned=true");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  await expect.poll(() => new URL(page.url()).searchParams.get("source_batch_kind")).toBeNull();
  await expect.poll(() => new URL(page.url()).searchParams.get("source_batch_id")).toBeNull();
  await expect.poll(() => new URL(page.url()).searchParams.get("source_batch_unassigned")).toBe("true");
  await expect.poll(() => pageQueries.some((query) => query.source_batch_unassigned === "true" && query.source_batch_kind === undefined && query.source_batch_id === undefined)).toBe(true);
  await page.getByTestId("exception-unassigned-batch-filter").click();

  await page.getByTestId("exception-quick-mine").click();
  await expect.poll(() => new URL(page.url()).searchParams.get("assignment")).toBe("mine");
  await expect.poll(() => pageQueries.some((query) => query.assignment === "mine")).toBe(true);
  await page.getByTestId("exception-quick-overdue").click();
  await expect.poll(() => pageQueries.some((query) => query.assignment === "mine" && query.sla_status === "overdue")).toBe(true);

  const exceptionSearch = page.getByPlaceholder("搜索案件编号、规则、对象或原因");
  await expect(exceptionSearch).toHaveAttribute("maxlength", "200");
  await expect(exceptionSearch).toHaveAttribute("aria-label", "搜索案件编号、规则、对象或原因");
  await exceptionSearch.fill("  ＡＢＣ   采购缺失  ");
  await expect.poll(() => pageQueries.some((query) => query.q === "ABC 采购缺失")).toBe(true);
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("ABC 采购缺失");
  await exceptionSearch.fill("x".repeat(250));
  const limitedQuery = await exceptionSearch.inputValue();
  expect(limitedQuery.length).toBeGreaterThan(0);
  expect(limitedQuery.length).toBeLessThanOrEqual(200);
  await expect.poll(() => pageQueries.some((query) => query.q === limitedQuery)).toBe(true);
  await exceptionSearch.fill("采购缺失");
  await expect.poll(() => pageQueries.some((query) => query.q === "采购缺失")).toBe(true);
  await page.getByLabel("聚合视图").selectOption("rule");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("采购缺失");
  await expect.poll(() => aggregationQueries.some((query) => query.group_by === "rule" && query.assignment === "mine" && query.sla_status === "overdue" && query.q === "采购缺失")).toBe(true);
  await expect(page.getByTestId("exception-aggregation-search-scope")).toContainText("基于当前全部筛选条件");
  await expect(page.getByText("库存负数", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "查看明细" }).click();
  await expect.poll(() => pageQueries.some((query) => query.rule_code === "inventory.negative_stock" && query.group_by === undefined)).toBe(true);

  await page.getByLabel("聚合视图").selectOption("batch");
  await expect(page.getByTestId("exception-aggregation-truncated")).toContainText("共 205 组");
  await expect(page.getByText("导入批次 91", { exact: true })).toBeVisible();
  await expect(page.getByText("库存核验批次 91", { exact: true })).toBeVisible();
  await page.getByText("导入批次 91", { exact: true }).locator("xpath=ancestor::tr").getByRole("button", { name: "查看明细" }).click();
  await expect.poll(() => pageQueries.some((query) => query.source_batch_kind === "import" && query.source_batch_id === "91" && query.source_batch_unassigned === undefined)).toBe(true);
  await expect.poll(() => new URL(page.url()).searchParams.get("source_batch_kind")).toBe("import");
  await expect.poll(() => new URL(page.url()).searchParams.get("source_batch_id")).toBe("91");

  await page.getByLabel("聚合视图").selectOption("batch");
  await expect(page.getByText("未关联批次", { exact: true })).toBeVisible();
  await page.getByText("未关联批次", { exact: true }).locator("xpath=ancestor::tr").getByRole("button", { name: "查看明细" }).click();
  await expect.poll(() => pageQueries.some((query) => query.source_batch_unassigned === "true" && query.source_batch_kind === undefined && query.source_batch_id === undefined)).toBe(true);
  await expect.poll(() => new URL(page.url()).searchParams.get("source_batch_unassigned")).toBe("true");
  await expect.poll(() => new URL(page.url()).searchParams.get("source_batch_kind")).toBeNull();
  await expect.poll(() => new URL(page.url()).searchParams.get("source_batch_id")).toBeNull();
  await expect(page.getByTestId("exception-unassigned-batch-filter")).toBeVisible();

  await page.getByText("库存数量异常", { exact: true }).click();
  const drawer = page.locator('[data-overlay-kind="drawer"][data-overlay-top="true"]');
  await expect(drawer.getByTestId("exception-business-evidence-inventory")).toContainText("推算结存");
  await expect(drawer.getByTestId("exception-diagnosis-structured")).toContainText("采购记录缺失");
  await expect(drawer.getByTestId("exception-active-job")).toContainText("DJ-801");
  await expect(drawer.getByTestId("exception-active-job")).toContainText("证据 evidence-v2");
  await expect(drawer.getByTestId("exception-diagnosis-progress")).toHaveAttribute("data-status", "queued");
  await expect(drawer.getByRole("progressbar", { name: "智能诊断进度" })).toHaveAttribute("aria-valuetext", "等待诊断资源");
  await expect(drawer.getByText("导入批次 91", { exact: true })).toBeVisible();
  await expect(drawer.getByRole("button", { name: "重试任务" })).toHaveCount(0);
  await expect(drawer.getByRole("button", { name: "取消任务" })).toHaveCount(0);
  await expect.poll(() => activeJobPolls, { timeout: 5_000 }).toBeGreaterThan(0);
  await drawer.getByTestId("exception-verify-note").fill("已核对采购单并重新同步");
  await drawer.getByRole("button", { name: "立即复检" }).click();
  await expect(drawer.getByTestId("exception-verification-result")).toContainText("复检通过");
  await expect(drawer.getByTestId("exception-verification-result")).toContainText("最新扫描未再发现负库存");
  await expect(drawer.getByTestId("exception-verification-evidence")).toHaveAttribute("data-evidence-current", "true");
  await expect(drawer.getByTestId("exception-diagnosis-progress")).toHaveCount(0);
  await expect(drawer.getByText("证据版本 evidence-v3", { exact: false })).toBeVisible();
  await expect(drawer.getByTestId("exception-business-evidence-inventory")).toContainText("复检后测试商品");
  expect(detailFetches).toBeGreaterThanOrEqual(2);
  expect(verifyPayload).toEqual({ note: "已核对采购单并重新同步", expected_evidence_version: "evidence-v2" });

  await drawer.getByRole("button", { name: "定位原始记录" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("return_case")).toBe(caseNo);
  await expect.poll(() => new URL(page.url()).searchParams.get("return_to")).toContain(`/exceptions`);
  await expect(page.getByTestId("exception-return-context")).toContainText(caseNo);
  await page.getByRole("button", { name: "返回异常案件" }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/exceptions");
  await expect.poll(() => new URL(page.url()).searchParams.get("open")).toBe(caseNo);
});

test("operations uses unified queue pagination, protects diagnosis-only actions, and renders quality metrics", async ({ page }) => {
  const requestedJobQueries: Array<Record<string, string>> = [];
  const qualityQueries: Array<Record<string, string>> = [];
  let circuitFixture: { open: boolean; consecutive_failures: number; retry_after_seconds: number; stale: boolean; source: "ai_worker" } | null = {
    open: false,
    consecutive_failures: 2,
    retry_after_seconds: 45,
    stale: false,
    source: "ai_worker"
  };
  let cancelPayload: Record<string, unknown> | null = null;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, { id: 10, username: "exception-operator", real_name: "异常运维", role: "admin", is_active: true, status: "active" });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, ["exception_center.view", "exception_center.policy_manage"]);
      return;
    }
    if (url.pathname === "/api/v1/admin/stage1/summary") {
      await fulfillJson(route, { users: 0, employees: 0, roles: 0, permissions: 0, authority_root_rules: 0, audit_logs: 0, import_batches: 0, customers: 0, products: 0, suppliers: 0 });
      return;
    }
    if (url.pathname === "/api/v1/exception-notifications") {
      await fulfillJson(route, []);
      return;
    }
    if (url.pathname === "/api/v1/exceptions/summary") {
      await fulfillJson(route, { ...summary, manual_ai_enabled: true, scheduled_ai_enabled: true, full_scan_enabled: true, digest_enabled: true });
      return;
    }
    if (url.pathname === "/api/v1/exception-ops/summary") {
      await fulfillJson(route, {
        generated_at: detectedAt,
        global_ai_enabled: true,
        provider_configured: true,
        provider_host: "https://hermes.example",
        model: "hermes-diagnosis",
        circuit: circuitFixture,
        diagnosis_jobs_by_status: { queued: 1, processing: 0, failed: 1 },
        diagnosis_jobs_by_trigger: { manual: { queued: 1, failed: 1 } },
        background_jobs_by_status: { queued: 0, processing: 0, failed: 1 },
        manual_queue_depth: 1,
        scheduled_queue_depth: 0,
        background_queue_depth: 0,
        heartbeats: [
          { service_type: "scheduler", instance_id: "scheduler-1", started_at: detectedAt, last_heartbeat_at: detectedAt, is_stale: false, is_healthy: true },
          { service_type: "worker", instance_id: "worker-1", started_at: detectedAt, last_heartbeat_at: detectedAt, is_stale: false, is_healthy: true },
          { service_type: "ai_worker", instance_id: "ai-1", started_at: detectedAt, last_heartbeat_at: detectedAt, is_stale: false, is_healthy: true }
        ],
        policy: { is_enabled: true, manual_ai_enabled: true, scheduled_ai_enabled: true, full_scan_enabled: true, digest_enabled: true, ai_concurrency: 2, scheduled_ai_batch_limit: 20 },
        manual_budget: { limit: 0, used: 3, remaining: null, unlimited: true },
        scheduled_budget: { limit: 0, used: 10, remaining: null, unlimited: true },
        last_full_scan_at: detectedAt,
        last_scan_duration_ms: 850,
        last_scan_created: 2,
        last_scan_new: 1,
        last_scan_reopened: 1,
        last_scan_evidence_updated: 3,
        last_scan_resolved: 4,
        last_scan_scanned: 120,
        diagnosis_completed_24h: 18,
        diagnosis_failed_24h: 2
      });
      return;
    }
    if (url.pathname === "/api/v1/exception-jobs/page") {
      const query = Object.fromEntries(url.searchParams);
      requestedJobQueries.push(query);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      await fulfillJson(route, offset === 30 ? {
        items: [{ id: 931, job_no: "BG-PAGE-2", job_kind: "background", job_type: "digest", status: "completed", attempts: 1, created_at: "2026-07-28T02:20:00Z" }],
        total: 31,
        limit: 30,
        offset: 30
      } : {
        items: [
          { id: 901, job_no: "DJ-QUEUED", job_kind: "diagnosis", job_type: "diagnosis", case_no: caseNo, evidence_version: "evidence-v2", trigger_type: "manual", status: "queued", attempts: 0, created_at: detectedAt },
          { id: 902, job_no: "DJ-FAILED", job_kind: "diagnosis", job_type: "diagnosis", case_no: caseNo, evidence_version: "evidence-v2", trigger_type: "manual", status: "failed", attempts: 2, error_message: "provider timeout", created_at: "2026-07-28T02:29:00Z" },
          { id: 903, job_no: "BG-FAILED", job_kind: "background", job_type: "full_scan", status: "failed", attempts: 3, error_message: "scan failed", created_at: "2026-07-28T02:28:00Z" }
        ],
        total: 31,
        limit: 30,
        offset: 0
      });
      return;
    }
    if (url.pathname === "/api/v1/exception-jobs/901/cancel") {
      cancelPayload = route.request().postDataJSON();
      await fulfillJson(route, { id: 901, job_no: "DJ-QUEUED", case_no: caseNo, evidence_version: "evidence-v2", trigger_type: "manual", status: "cancelled", reused: false, attempts: 0, created_at: detectedAt });
      return;
    }
    if (url.pathname === "/api/v1/exception-diagnoses/quality") {
      qualityQueries.push(Object.fromEntries(url.searchParams));
      await fulfillJson(route, {
        generated_at: detectedAt,
        total_diagnoses: 20,
        feedback_count: 10,
        feedback_rate: 0.5,
        helpful_rate: 0.8,
        feedback_coverage_rate: 0.5,
        rated_diagnoses: 10,
        helpful: 7,
        partial: 2,
        incorrect: 1,
        unrated: 10,
        positive_rate: 0.9,
        evidence_reference_valid_rate: 0.95,
        average_confidence: 0.92,
        average_latency_ms: 1200,
        average_resolution_hours: 4.5,
        prompt_tokens: 1000,
        completion_tokens: 500,
        total_tokens: 1500,
        usage_reported_count: 18,
        usage_missing_count: 2,
        usage_completeness_rate: 0.9,
        by_feedback: { helpful: 7, partial: 2, incorrect: 1 },
        by_disposition: { actionable: 8, manual_review: 9, blocked: 3 },
        by_root_cause_code: { missing_purchase: 6 },
        by_contract_version: { v1: 20 },
        by_domain: [],
        by_rule: [],
        by_model: [],
        by_prompt_version: [],
        rules: [{ domain: "inventory", rule_code: "inventory.negative_stock", diagnoses: 12, feedback_count: 8, helpful: 6, partial: 1, incorrect: 1, helpful_rate: 0.875, average_confidence: 0.94, average_resolution_hours: 3.2 }]
      });
      return;
    }
    await fulfillJson(route, { items: [], total: 0, limit: 30, offset: 0 });
  });

  await page.goto("index.html");
  await page.evaluate(() => {
    window.history.replaceState(null, "", "/exceptions?view=operations");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  await expect(page.getByTestId("exception-operations-panel")).toBeVisible();
  await expect(page.getByText("AI Worker", { exact: true })).toBeVisible();
  await expect(page.getByText("hermes-diagnosis", { exact: true })).toBeVisible();
  await expect(page.getByText("3 / 不限量", { exact: true })).toBeVisible();
  await expect(page.getByText("10 / 不限量", { exact: true })).toBeVisible();
  const circuitStatus = page.getByTestId("exception-circuit-status");
  await expect(circuitStatus).toHaveAttribute("data-circuit-state", "closed");
  await expect(circuitStatus).toContainText("正常");
  await expect(page.getByTestId("exception-circuit-status")).toContainText("连续失败 2");
  await expect(page.getByTestId("exception-circuit-status")).toContainText("重试等待 45 秒");
  await expect(page.getByTestId("exception-circuit-status")).toContainText("AI Worker 状态有效");
  await expect(page.getByTestId("exception-circuit-status")).toContainText("ai_worker");

  circuitFixture = { open: true, consecutive_failures: 5, retry_after_seconds: 300, stale: false, source: "ai_worker" };
  await page.getByTestId("exception-operations-panel").getByRole("button", { name: "刷新" }).click();
  await expect(circuitStatus).toHaveAttribute("data-circuit-state", "open");
  await expect(circuitStatus).toContainText("已熔断");
  await expect(circuitStatus).toContainText("重试等待 300 秒");

  circuitFixture = { open: false, consecutive_failures: 1, retry_after_seconds: 0, stale: true, source: "ai_worker" };
  await page.getByTestId("exception-operations-panel").getByRole("button", { name: "刷新" }).click();
  await expect(circuitStatus).toHaveAttribute("data-circuit-state", "stale");
  await expect(circuitStatus).toContainText("状态已过期");
  await expect(circuitStatus).toContainText("上次状态正常");

  circuitFixture = null;
  await page.getByTestId("exception-operations-panel").getByRole("button", { name: "刷新" }).click();
  await expect(circuitStatus).toHaveAttribute("data-circuit-state", "unavailable");
  await expect(circuitStatus).toContainText("不能判定服务正常");
  await expect.poll(() => requestedJobQueries.some((query) => query.job_kind === "all" && query.offset === "0")).toBe(true);
  expect(requestedJobQueries.some((query) => query.job_kind === "diagnosis" || query.job_kind === "background")).toBe(false);
  await expect(page.getByText("DJ-QUEUED", { exact: true })).toBeVisible();
  await expect(page.getByText("BG-FAILED", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "重试任务 DJ-FAILED" })).toBeVisible();
  await expect(page.getByRole("button", { name: "重试任务 BG-FAILED" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "取消任务 BG-FAILED" })).toHaveCount(0);

  await expect(page.getByTestId("exception-job-pagination")).toContainText("共 2 页");
  await page.getByTestId("exception-job-pagination").getByRole("button", { name: "下一页" }).click();
  await expect.poll(() => requestedJobQueries.some((query) => query.job_kind === "all" && query.offset === "30")).toBe(true);
  await expect(page.getByText("BG-PAGE-2", { exact: true })).toBeVisible();
  await page.getByTestId("exception-job-pagination").getByRole("button", { name: "上一页" }).click();
  await expect(page.getByText("DJ-QUEUED", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "取消任务 DJ-QUEUED" }).click();
  const confirmCancel = page.getByTestId("exception-job-cancel-confirm");
  await expect(confirmCancel.getByRole("button", { name: "确认取消" })).toBeDisabled();
  await confirmCancel.getByTestId("exception-job-cancel-reason").fill("运维核对后取消重复任务");
  await confirmCancel.getByRole("button", { name: "确认取消" }).click();
  await expect.poll(() => cancelPayload).toEqual({ reason: "运维核对后取消重复任务" });

  await page.getByRole("button", { name: "诊断质量" }).click();
  await expect(page.getByTestId("exception-diagnosis-quality")).toContainText("证据引用有效率");
  await expect(page.getByTestId("exception-diagnosis-quality")).toContainText("95%");
  await expect(page.getByTestId("exception-diagnosis-quality")).toContainText("Token 上报 18/20");
  await expect(page.getByTestId("exception-diagnosis-quality")).toContainText("完整率 90%");
  await expect(page.getByTestId("exception-diagnosis-quality")).toContainText("缺失 2");
  await expect(page.getByText("inventory.negative_stock", { exact: true })).toBeVisible();

  const qualityPanel = page.getByTestId("exception-diagnosis-quality");
  const qualityRequestCount = qualityQueries.length;
  await qualityPanel.getByLabel("诊断开始时间").fill("2026-07-28T12:00");
  await qualityPanel.getByLabel("诊断结束时间").fill("2026-07-28T11:00");
  await qualityPanel.getByRole("button", { name: "应用筛选" }).click();
  await expect(qualityPanel.getByTestId("exception-quality-filter-error")).toContainText("诊断开始时间不能晚于结束时间");
  expect(qualityQueries).toHaveLength(qualityRequestCount);

  await qualityPanel.getByLabel("诊断结束时间").fill("2026-07-29T13:30");
  const expectedRange = await page.evaluate(() => ({
    diagnosed_from: new Date("2026-07-28T12:00").toISOString(),
    diagnosed_to: new Date("2026-07-29T13:30").toISOString()
  }));
  await qualityPanel.getByRole("button", { name: "应用筛选" }).click();
  await expect.poll(() => qualityQueries.at(-1)).toEqual(expectedRange);

  await qualityPanel.getByRole("button", { name: "清除" }).click();
  await expect.poll(() => qualityQueries.at(-1)).toEqual({});
  await expect(qualityPanel.getByLabel("诊断开始时间")).toHaveValue("");
  await expect(qualityPanel.getByLabel("诊断结束时间")).toHaveValue("");
});

test("policy drawer sends a minimal CAS patch and surfaces stale administrator edits", async ({ page }) => {
  let policy = {
    policy_key: "default",
    is_enabled: true,
    manual_ai_enabled: false,
    scheduled_ai_enabled: false,
    full_scan_enabled: false,
    digest_enabled: false,
    full_scan_cron: "30 2 * * *",
    digest_cron: "30 8 * * *",
    ai_daily_limit: 20,
    ai_batch_limit: 20,
    manual_ai_daily_limit: 20,
    scheduled_ai_daily_limit: 0,
    scheduled_ai_batch_limit: 20,
    ai_concurrency: 1,
    stale_diagnosis_hours: 24,
    settings: {},
    updated_at: "2026-07-29T08:00:00Z"
  };
  const patchPayloads: Array<Record<string, unknown>> = [];
  let rejectNextPatch = false;

  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, { id: 12, username: "policy-admin", real_name: "策略管理员", role: "admin", is_active: true, status: "active" });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, ["exception_center.view", "exception_center.policy_manage"]);
      return;
    }
    if (url.pathname === "/api/v1/admin/stage1/summary") {
      await fulfillJson(route, { users: 0, employees: 0, roles: 0, permissions: 0, authority_root_rules: 0, audit_logs: 0, import_batches: 0, customers: 0, products: 0, suppliers: 0 });
      return;
    }
    if (url.pathname === "/api/v1/exception-notifications") {
      await fulfillJson(route, []);
      return;
    }
    if (url.pathname === "/api/v1/exceptions/summary") {
      await fulfillJson(route, summary);
      return;
    }
    if (url.pathname === "/api/v1/exceptions/page") {
      await fulfillJson(route, { items: [], total: 0, limit: 30, offset: 0 });
      return;
    }
    if (url.pathname === "/api/v1/exception-policies" && route.request().method() === "GET") {
      await fulfillJson(route, policy);
      return;
    }
    if (url.pathname === "/api/v1/exception-policies" && route.request().method() === "PATCH") {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      patchPayloads.push(payload);
      if (rejectNextPatch) {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "Policy changed" }) });
        return;
      }
      policy = {
        ...policy,
        manual_ai_enabled: Boolean(payload.manual_ai_enabled),
        updated_at: "2026-07-29T08:05:00Z"
      };
      await fulfillJson(route, policy);
      return;
    }
    await fulfillJson(route, { items: [], total: 0, limit: 30, offset: 0 });
  });

  await page.goto("index.html");
  await page.evaluate(() => {
    window.history.replaceState(null, "", "/exceptions");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  await page.getByRole("button", { name: "巡检策略" }).click();
  const drawer = page.getByRole("dialog", { name: "异常巡检策略" });
  const manualToggle = drawer.getByRole("checkbox", { name: "允许人工智能诊断" });
  await manualToggle.check();
  await drawer.getByRole("button", { name: "保存策略" }).click();
  await expect.poll(() => patchPayloads.length).toBe(1);
  expect(patchPayloads[0]).toEqual({
    expected_updated_at: "2026-07-29T08:00:00Z",
    manual_ai_enabled: true
  });
  await expect(drawer.getByRole("button", { name: "没有待保存修改" })).toBeDisabled();

  rejectNextPatch = true;
  await manualToggle.uncheck();
  await drawer.getByRole("button", { name: "保存策略" }).click();
  await expect.poll(() => patchPayloads.length).toBe(2);
  expect(patchPayloads[1]).toEqual({
    expected_updated_at: "2026-07-29T08:05:00Z",
    manual_ai_enabled: false
  });
  await expect(drawer).toContainText("巡检策略已被其他管理员更新，请刷新后重新修改。");
});

for (const deniedStatus of [403, 404]) {
  test(`active diagnosis polling stops on ${deniedStatus} and refreshes access plus detail`, async ({ page }) => {
    const jobId = 810 + deniedStatus;
    let permissionCalls = 0;
    let detailCalls = 0;
    let pollCalls = 0;
    let accessRevoked = false;
    await page.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/v1/auth/me") {
        await fulfillJson(route, { id: 12, username: "poll-owner", real_name: "轮询负责人", role: "data_operator", is_active: true, status: "active" });
        return;
      }
      if (url.pathname === "/api/v1/auth/my-permissions") {
        permissionCalls += 1;
        await fulfillJson(route, deniedStatus === 403 && accessRevoked
          ? ["exception_center.view", "inventory_snapshot.view"]
          : ["exception_center.view", "exception_center.diagnose", "inventory_snapshot.view"]);
        return;
      }
      if (url.pathname === "/api/v1/admin/stage1/summary") {
        await fulfillJson(route, { users: 0, employees: 0, roles: 0, permissions: 0, authority_root_rules: 0, audit_logs: 0, import_batches: 0, customers: 0, products: 0, suppliers: 0 });
        return;
      }
      if (url.pathname === "/api/v1/exception-notifications") {
        await fulfillJson(route, []);
        return;
      }
      if (url.pathname === "/api/v1/exceptions/summary") {
        await fulfillJson(route, { ...summary, ai_enabled: true, unread_notifications: 0 });
        return;
      }
      if (url.pathname === "/api/v1/exceptions/page") {
        await fulfillJson(route, { items: [caseItem], total: 1, limit: 30, offset: 0 });
        return;
      }
      if (url.pathname === `/api/v1/exceptions/${caseNo}`) {
        detailCalls += 1;
        await fulfillJson(route, {
          ...caseItem,
          evidence: { product_code: "P-0017", stock_qty: -12 },
          diagnosis: null,
          diagnoses: [],
          actions: [],
          events: [],
          active_diagnosis_job: { id: jobId, job_no: `DJ-${deniedStatus}`, case_no: caseNo, evidence_version: "evidence-v2", trigger_type: "manual", status: "queued", reused: false, attempts: 0, created_at: detectedAt }
        });
        return;
      }
      if (url.pathname === `/api/v1/exception-jobs/${jobId}`) {
        pollCalls += 1;
        if (deniedStatus === 403) accessRevoked = true;
        await route.fulfill({
          status: deniedStatus,
          contentType: "application/json",
          body: JSON.stringify({ detail: deniedStatus === 403 ? "permission changed" : "job missing" })
        });
        return;
      }
      await fulfillJson(route, {});
    });

    await page.goto("index.html");
    await page.evaluate(() => {
      window.history.replaceState(null, "", "/exceptions");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.getByText("库存数量异常", { exact: true }).click();
    const drawer = page.locator('[data-overlay-kind="drawer"][data-overlay-top="true"]');
    const pollIssue = drawer.getByTestId("exception-job-poll-issue");
    await expect(pollIssue).toBeVisible({ timeout: 6_000 });
    await expect(pollIssue).toHaveAttribute("data-poll-stopped", "true");
    await expect(pollIssue).toContainText("轮询已停止");
    await expect.poll(() => permissionCalls).toBeGreaterThanOrEqual(2);
    await expect.poll(() => detailCalls).toBeGreaterThanOrEqual(2);
    await page.waitForTimeout(2_300);
    expect(pollCalls).toBe(1);
  });
}

test("active diagnosis polling exposes 5xx backoff and supports immediate manual retry", async ({ page }) => {
  const jobId = 850;
  let pollCalls = 0;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, { id: 13, username: "retry-owner", real_name: "重试负责人", role: "data_operator", is_active: true, status: "active" });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, ["exception_center.view", "exception_center.diagnose", "inventory_snapshot.view"]);
      return;
    }
    if (url.pathname === "/api/v1/admin/stage1/summary") {
      await fulfillJson(route, { users: 0, employees: 0, roles: 0, permissions: 0, authority_root_rules: 0, audit_logs: 0, import_batches: 0, customers: 0, products: 0, suppliers: 0 });
      return;
    }
    if (url.pathname === "/api/v1/exception-notifications") {
      await fulfillJson(route, []);
      return;
    }
    if (url.pathname === "/api/v1/exceptions/summary") {
      await fulfillJson(route, { ...summary, ai_enabled: true, unread_notifications: 0 });
      return;
    }
    if (url.pathname === "/api/v1/exceptions/page") {
      await fulfillJson(route, { items: [caseItem], total: 1, limit: 30, offset: 0 });
      return;
    }
    if (url.pathname === `/api/v1/exceptions/${caseNo}`) {
      await fulfillJson(route, {
        ...caseItem,
        evidence: { product_code: "P-0017", stock_qty: -12 },
        diagnosis: null,
        diagnoses: [],
        actions: [],
        events: [],
        active_diagnosis_job: { id: jobId, job_no: "DJ-RETRY", case_no: caseNo, evidence_version: "evidence-v2", trigger_type: "manual", status: "queued", reused: false, attempts: 0, created_at: detectedAt }
      });
      return;
    }
    if (url.pathname === `/api/v1/exception-jobs/${jobId}`) {
      pollCalls += 1;
      if (pollCalls === 1) {
        await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporarily unavailable" }) });
      } else {
        await fulfillJson(route, { id: jobId, job_no: "DJ-RETRY", case_no: caseNo, evidence_version: "evidence-v2", trigger_type: "manual", status: "processing", reused: false, attempts: 1, created_at: detectedAt });
      }
      return;
    }
    await fulfillJson(route, {});
  });

  await page.goto("index.html");
  await page.evaluate(() => {
    window.history.replaceState(null, "", "/exceptions");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await page.getByText("库存数量异常", { exact: true }).click();
  const drawer = page.locator('[data-overlay-kind="drawer"][data-overlay-top="true"]');
  const pollIssue = drawer.getByTestId("exception-job-poll-issue");
  await expect(pollIssue).toBeVisible({ timeout: 6_000 });
  await expect(pollIssue).toHaveAttribute("data-poll-stopped", "false");
  await expect(pollIssue).toContainText("2 秒后重试");
  await pollIssue.getByRole("button", { name: "立即重试状态刷新" }).click();
  await expect.poll(() => pollCalls).toBeGreaterThanOrEqual(2);
  await expect(drawer.getByTestId("exception-diagnosis-progress")).toHaveAttribute("data-status", "processing");
  await expect(drawer.getByRole("progressbar", { name: "智能诊断进度" })).toHaveAttribute("aria-valuetext", "正在分析证据并生成诊断");
  await expect(pollIssue).toHaveCount(0);
  await expect(drawer.getByTestId("exception-active-job")).toContainText("诊断中");
});

test("users without policy permission fall back from protected exception views", async ({ page }) => {
  let protectedCalls = 0;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, { id: 11, username: "exception-viewer", real_name: "异常查看员", role: "viewer", is_active: true, status: "active" });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, ["exception_center.view"]);
      return;
    }
    if (url.pathname === "/api/v1/admin/stage1/summary") {
      await fulfillJson(route, { users: 0, employees: 0, roles: 0, permissions: 0, authority_root_rules: 0, audit_logs: 0, import_batches: 0, customers: 0, products: 0, suppliers: 0 });
      return;
    }
    if (url.pathname === "/api/v1/exception-notifications") {
      await fulfillJson(route, []);
      return;
    }
    if (url.pathname === "/api/v1/exceptions/summary") {
      await fulfillJson(route, { ...summary, manual_ai_enabled: false, scheduled_ai_enabled: false, full_scan_enabled: false, digest_enabled: false });
      return;
    }
    if (url.pathname === "/api/v1/exceptions/page") {
      await fulfillJson(route, { items: [caseItem], total: 1, limit: 30, offset: 0 });
      return;
    }
    if (url.pathname === `/api/v1/exceptions/${caseNo}`) {
      await fulfillJson(route, {
        ...caseItem,
        evidence: {},
        diagnoses: [],
        actions: [],
        events: [],
        active_diagnosis_job: { id: 804, job_no: "DJ-NO-PERMISSION", case_no: caseNo, evidence_version: "evidence-v2", trigger_type: "manual", status: "queued", attempts: 0, created_at: detectedAt }
      });
      return;
    }
    if (
      url.pathname === "/api/v1/exception-ops/summary"
      || url.pathname === "/api/v1/exception-diagnoses/quality"
      || url.pathname === "/api/v1/exception-policies"
      || url.pathname.startsWith("/api/v1/exception-jobs/")
    ) protectedCalls += 1;
    await fulfillJson(route, {});
  });

  await page.goto("index.html");
  await page.evaluate(() => {
    window.history.replaceState(null, "", "/exceptions?view=quality");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  await expect(page.getByRole("heading", { name: "统一异常中心" })).toBeVisible();
  await expect(page.getByRole("button", { name: "运行运维" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "诊断质量" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "巡检策略" })).toHaveCount(0);
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBeNull();
  await page.getByText("库存数量异常", { exact: true }).click();
  const drawer = page.locator('[data-overlay-kind="drawer"][data-overlay-top="true"]');
  await expect(drawer.getByTestId("exception-active-job")).toContainText("DJ-NO-PERMISSION");
  await expect(drawer.getByText("当前证据已留存，但没有可按业务口径展示的标准字段。", { exact: false })).toBeVisible();
  await page.waitForTimeout(2_200);
  expect(protectedCalls).toBe(0);
});

test("legacy pages receive the structured global API error notice", async ({ page }) => {
  const requestId = "req-global-api-error-001";
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, {
        id: 6,
        username: "dashboard-viewer",
        real_name: "Dashboard Viewer",
        role: "data_operator",
        is_active: true,
        status: "active"
      });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, ["dashboard.view", "inventory_snapshot.view"]);
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
    if (url.pathname === "/api/v1/dashboard/overview") {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        headers: { "X-Request-ID": requestId },
        body: JSON.stringify({
          detail: {
            error_code: "inventory.unit_missing",
            message: "Inventory unit mapping is incomplete.",
            request_id: requestId,
            module: "inventory",
            resource_type: "product",
            resource_id: "P-0017",
            retryable: false,
            action_path: "/inventory?attention_state=needs_attention&product_code=P-0017",
            field_errors: [{ field: "base_unit", message: "Unit mapping is missing.", ignored_raw_value: "must-not-render" }]
          }
        })
      });
      return;
    }
    await fulfillJson(route, {});
  });

  await page.goto("index.html");

  const notice = page.getByTestId("global-api-error");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("inventory.unit_missing");
  await expect(notice).toContainText("Unit mapping is missing.");
  await expect(notice).toContainText(requestId);
  await expect(notice).not.toContainText("must-not-render");
  await expect(notice.getByTestId("api-error-copy")).toBeVisible();
  await expect(notice.getByTestId("api-error-action")).toBeVisible();
  await notice.getByTestId("api-error-close").click();
  await expect(notice).toHaveCount(0);
});

test("authentication failures do not create global API error noise", async ({ page }) => {
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: { error_code: "auth.invalid_session", message: "Session expired." } })
    });
  });

  await page.goto("index.html");

  await expect(page.locator("form")).toBeVisible();
  await expect(page.getByTestId("global-api-error")).toHaveCount(0);
});
