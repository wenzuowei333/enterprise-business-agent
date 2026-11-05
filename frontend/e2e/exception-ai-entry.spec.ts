import { expect, test, type Page, type Route } from "@playwright/test";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

const runtime = {
  configured: true,
  model: "GLM-5.2",
  provider_host: "provider.invalid",
  source: "exception_center_global_ai",
  direct_db_enabled: false,
  skills: [{ operation: "dashboard.summary", label: "经营摘要", description: "汇总有权上下文", write_effect: "readonly" }]
};

const emptySummary = {
  total: 0,
  open: 0,
  action_required: 0,
  processing: 0,
  blocked: 0,
  resolved: 0,
  ignored: 0,
  unread_notifications: 0,
  ai_enabled: true,
  ai_chat_enabled: true,
  ai_case_analysis_enabled: false,
  actions_enabled: true,
  manual_ai_enabled: true,
  scheduled_ai_enabled: false,
  full_scan_enabled: false,
  digest_enabled: false,
  by_domain: {},
  by_severity: {},
  by_occurrence: {}
};

async function mockApplication(page: Page, permissions: string[], onApiRequest?: (path: string) => void) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    onApiRequest?.(path);
    if (path === "/api/v1/auth/me") return fulfillJson(route, { id: 1, username: "admin", real_name: "管理员", role: "admin", is_active: true, status: "active" });
    if (path === "/api/v1/auth/my-permissions") return fulfillJson(route, permissions);
    if (path === "/api/v1/admin/stage1/summary") return fulfillJson(route, { users: 1, employees: 0, roles: 0, permissions: permissions.length, authority_root_rules: 0, audit_logs: 0, import_batches: 0, customers: 0, products: 0, suppliers: 0 });
    if (path === "/api/v1/exceptions/summary") return fulfillJson(route, emptySummary);
    if (path === "/api/v1/exceptions/page") return fulfillJson(route, { items: [], total: 0, limit: 30, offset: 0 });
    if (path === "/api/v1/exception-notifications") return fulfillJson(route, []);
    if (path === "/api/v1/ai/chat/conversations") return fulfillJson(route, []);
    if (path === "/api/v1/crm/summary") return fulfillJson(route, { active_projects: 0, pending_project_approvals: 0, task_total: 0, due_today_tasks: 0, overdue_no_feedback_tasks: 0, open_work_items: 0, closed_tasks: 0, valid_feedback_tasks: 0, valid_feedback_rate: 0, generated_at: "2026-08-30T00:00:00Z" });
    if (path === "/api/v1/crm/daily-summary") return fulfillJson(route, { date: "2026-08-30", due_tasks: [], overdue_tasks: [], task_total: 0, due_count: 0, overdue_count: 0, responsible_user_ids: [], missing_responsible_user_ids: [], generated_at: "2026-08-30T00:00:00Z" });
    if (["/api/v1/crm/projects/page", "/api/v1/crm/tasks/page", "/api/v1/work-items/page", "/api/v1/crm/assistant/insights/page", "/api/v1/crm/assistant/actions/page"].includes(path)) return fulfillJson(route, { items: [], total: 0, limit: 30, offset: 0 });
    if (path === "/api/v1/crm/assistant/runtime") return fulfillJson(route, runtime);
    if (path === "/api/v1/crm/assistant/agents") return fulfillJson(route, { runtime, status_counts: {}, source_counts: {}, operation_counts: {}, pending_actions: 0, recent_calls: [], last_call_at: null });
    if (path === "/api/v1/crm/assistant/messages") return fulfillJson(route, []);
    if (path === "/api/v1/ai/actions/catalog") return fulfillJson(route, [
      { action_type: "crm_insight.review", domain: "crm", label: "复核 CRM 判断", risk_level: "medium", required_permissions: ["crm_insight.review"], requires_confirmation: true, available: true, blockers: [] },
      { action_type: "rebuild_inventory_flow", domain: "inventory", label: "重建库存流转", risk_level: "high", required_permissions: ["exception_center.action_execute", "inventory_check.upload"], requires_confirmation: true, available: true, blockers: [] }
    ]);
    if (path === "/api/v1/ai/actions/proposals") return fulfillJson(route, { items: [{ id: 11, proposal_no: "AI-CRM-PROP-11", domain: "crm", action_type: "crm_insight.review", resource_type: "crm_project_insight", resource_id: "11", status: "proposed", review_status: "pending", risk_level: "medium", requires_confirmation: true, parameters: {}, impact: {}, source_refs: [], executable: true, blockers: [], created_at: "2026-08-30T00:00:00Z", updated_at: "2026-08-30T00:00:00Z", reviewed_at: null }], total: 1, limit: 50, offset: 0 });
    if (path === "/api/v1/ai/actions/executions") return fulfillJson(route, { items: [], total: 0, limit: 30, offset: 0 });
    if (path === "/api/v1/ai/actions/proposals/AI-CRM-PROP-11/crm-review") return fulfillJson(route, { execution_no: "AI-CRM-EXEC-11", proposal_no: "AI-CRM-PROP-11", status: "completed", idempotency_key: "server-redacted", attempts: 1, executor_identity: "human_confirmed_action_center", result: {}, verification: { human_confirmed: true }, completed_at: "2026-08-30T00:01:00Z" });
    return fulfillJson(route, { detail: "not mocked" }, 404);
  });
}

async function goToRoute(page: Page, path: string, beforeNavigate?: () => void) {
  await page.goto("index.html");
  await expect(page.getByRole("button", { name: "管理员" })).toBeVisible();
  beforeNavigate?.();
  await page.evaluate((nextPath) => {
    window.history.replaceState(null, "", nextPath);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
}

test("legacy CRM assistant route opens the streaming exception chat", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const requestedPaths: string[] = [];
  await mockApplication(page, ["exception_center.view", "crm_insight.view", "crm_insight.generate", "crm_insight.review", "crm_project.view"], (path) => requestedPaths.push(path));
  await page.addInitScript(() => {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (!url.endsWith("/api/v1/ai/chat/streams")) return nativeFetch(input, init);
      const encoder = new TextEncoder();
      const frame = (event: string, data: Record<string, unknown>) => encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(frame("run_started", { run_no: "AI-RUN-E2E", conversation_no: "AI-CHAT-E2E", request_id: "REQ-E2E" }));
          controller.enqueue(frame("message_started", { message_no: "AI-MSG-E2E" }));
          controller.enqueue(frame("delta", { text: "第一段已经到达" }));
          window.setTimeout(() => {
            controller.enqueue(frame("delta", { text: "，最终回答完成。" }));
            controller.enqueue(frame("message_completed", { message: { message_no: "AI-MSG-E2E", sequence_no: 2, role: "assistant", content: "第一段已经到达，最终回答完成。", status: "completed", source_refs: [], created_at: "2026-08-31T00:00:00Z" } }));
            controller.enqueue(frame("done", { run_no: "AI-RUN-E2E" }));
            controller.close();
          }, 500);
        }
      });
      return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
    };
  });
  await goToRoute(page, "/crm/assistant?source=legacy", () => requestedPaths.splice(0));

  await expect(page).toHaveURL(/\/exceptions\?assistant=open&source=legacy$/);
  await expect(page.getByTestId("exception-ai-chat-overlay")).toBeVisible();
  await expect(page.getByRole("heading", { name: "异常处理助手", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "汇总当前高风险异常" }).click();
  await expect(page.getByText("第一段已经到达", { exact: true })).toBeVisible();
  await expect(page.getByText("第一段已经到达，最终回答完成。", { exact: true })).toHaveCount(0);
  await expect(page.getByText("第一段已经到达，最终回答完成。", { exact: true })).toBeVisible();
  await expect(page.getByText("GLM-5.2 · 分析与受控处置", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "AI 协同" })).toHaveCount(0);
  const desktopDrawer = await page.getByRole("dialog", { name: "异常处理助手" }).boundingBox();
  expect(desktopDrawer?.width).toBe(520);
  await page.screenshot({ path: testInfo.outputPath("exception-ai-chat-desktop.png"), fullPage: true });
});

test("narrow viewport uses a full-screen chat sheet without overflow", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApplication(page, ["exception_center.view", "crm_insight.view"]);
  await page.goto("index.html");
  await expect(page.getByTestId("app-workspace")).toBeVisible();
  await page.evaluate(() => {
    window.history.replaceState(null, "", "/exceptions?assistant=open");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  const sheet = page.getByRole("dialog", { name: "异常处理助手" });
  await expect(sheet).toBeVisible();
  await page.waitForTimeout(250);
  const box = await sheet.boundingBox();
  expect(box?.x).toBeLessThanOrEqual(0.5);
  expect(box?.width).toBeGreaterThanOrEqual(389.5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("exception-ai-chat-mobile.png") });
});

test("case row asks AI once with case number only and renders controlled actions", async ({ page }) => {
  const caseNo = "EXC-CASE-AI-0001";
  const caseItem = {
    id: 41,
    case_no: caseNo,
    domain: "inventory",
    rule_code: "inventory.negative_stock",
    title: "库存数量异常",
    severity: "critical",
    status: "open",
    occurrence_type: "new",
    occurrence_cycle: 1,
    rule_version: "v1",
    resource_type: "inventory_snapshot",
    resource_id: "17",
    resource_code: "P-0017",
    resource_name: "测试商品",
    source_type: "inventory_snapshot_quality",
    source_id: "17",
    source_batch_kind: "import",
    source_batch_id: 91,
    data_date: "2026-08-31",
    evidence_version: "evidence-v3",
    reason: "库存结存为负数",
    initial_guidance: "核对上游单据后重新同步",
    action_path: "/inventory?product_code=P-0017",
    affected_rows: 1,
    affected_quantity: "-12",
    assignee_user_id: null,
    assignee_name: null,
    due_at: null,
    detected_at: "2026-08-31T01:00:00Z",
    last_seen_at: "2026-08-31T01:00:00Z",
    metadata: {},
  };
  await mockApplication(page, ["exception_center.view", "crm_insight.view"]);
  await page.route("**/api/v1/exceptions/summary", (route) => fulfillJson(route, { ...emptySummary, total: 1, open: 1, ai_case_analysis_enabled: true }));
  await page.route("**/api/v1/exceptions/page**", (route) => fulfillJson(route, { items: [caseItem], total: 1, limit: 30, offset: 0 }));
  await page.addInitScript((targetCaseNo) => {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (!url.endsWith("/api/v1/ai/chat/streams")) return nativeFetch(input, init);
      (window as Window & { __caseAiRequest?: unknown }).__caseAiRequest = JSON.parse(String(init?.body || "{}"));
      (window as Window & { __caseAiCalls?: number }).__caseAiCalls = ((window as Window & { __caseAiCalls?: number }).__caseAiCalls || 0) + 1;
      const encoder = new TextEncoder();
      const frame = (event: string, data: Record<string, unknown>) => encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(frame("run_started", { run_no: "AI-RUN-CASE", conversation_no: "AI-CHAT-CASE", request_id: "REQ-CASE" }));
          controller.enqueue(frame("context_ready", { label: `当前案件 · ${targetCaseNo}`, case_no: targetCaseNo, title: "库存数量异常", severity: "critical", status: "open", evidence_version: "evidence-v3", conversation_reused: false }));
          controller.enqueue(frame("message_started", { message_no: "AI-MSG-CASE" }));
          window.setTimeout(() => {
            controller.enqueue(frame("delta", { text: "## 结论摘要\n库存结存异常，需要核对上游单据。" }));
            const artifact = { type: "exception_case_analysis", case: { case_no: targetCaseNo, title: "库存数量异常", severity: "critical", status: "open", evidence_version: "evidence-v3" }, action_path: "/inventory?product_code=P-0017", available_actions: ["rebuild_inventory_flow"] };
            controller.enqueue(frame("artifact", { artifact }));
            controller.enqueue(frame("message_completed", { message: { message_no: "AI-MSG-CASE", sequence_no: 2, role: "assistant", content: "## 结论摘要\n库存结存异常，需要核对上游单据。", status: "completed", source_refs: [], context_meta: artifact.case, artifacts: [artifact], created_at: "2026-08-31T01:01:00Z" } }));
            controller.enqueue(frame("done", { run_no: "AI-RUN-CASE" }));
            controller.close();
          }, 250);
        }
      });
      return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
    };
  }, caseNo);
  await goToRoute(page, "/exceptions");
  await page.getByTitle(`询问 AI 分析 ${caseNo}`).click();
  await expect(page.getByTestId("exception-ai-case-context")).toContainText(caseNo);
  await expect(page.getByTestId("exception-ai-progress")).toBeVisible();
  await expect(page.getByTitle("AI 正在分析其他案件")).toBeDisabled();
  await expect(page.getByRole("heading", { name: "结论摘要" })).toBeVisible();
  await expect(page.getByRole("button", { name: "进入受控动作" })).toBeVisible();
  const request = await page.evaluate(() => (window as Window & { __caseAiRequest?: Record<string, unknown> }).__caseAiRequest);
  expect(request).toMatchObject({ operation: "exception.case_analysis", context: { scope: "case", filters: {}, case_nos: [caseNo] } });
  expect(JSON.stringify(request)).not.toContain("库存结存为负数");
  expect(await page.evaluate(() => (window as Window & { __caseAiCalls?: number }).__caseAiCalls)).toBe(1);
});

test("assistant messages render safe GFM markdown", async ({ page }, testInfo) => {
  await mockApplication(page, ["exception_center.view", "crm_insight.view"]);
  await page.route("**/api/v1/ai/chat/conversations", (route) => fulfillJson(route, [{ conversation_no: "AI-CHAT-MARKDOWN", channel: "exception_center_web", status: "active", title: "Markdown 验收", model_name: "GLM-5.2", message_count: 2, last_message: "高风险异常汇总", created_at: "2026-08-31T00:00:00Z", updated_at: "2026-08-31T00:01:00Z" }]));
  await page.route("**/api/v1/ai/chat/conversations/AI-CHAT-MARKDOWN/messages", (route) => fulfillJson(route, [
    { message_no: "MD-1", sequence_no: 1, role: "user", content: "请汇总异常", status: "completed", source_refs: [], created_at: "2026-08-31T00:00:00Z" },
    { message_no: "MD-2", sequence_no: 2, role: "assistant", content: "## 高风险异常汇总\n\n> 数据仅供人工核对\n\n| 严重度 | 合计 |\n| --- | ---: |\n| High | **4** |\n\n- [x] 已完成权限裁剪\n- [ ] 待人工确认\n\n[查看说明](https://example.com)\n\n![远程图片](https://example.com/tracker.png)\n\n<script>window.__unsafeMarkdown = true</script>", status: "completed", source_refs: [], created_at: "2026-08-31T00:01:00Z" },
  ]));
  await goToRoute(page, "/exceptions?assistant=open");
  await page.getByRole("button", { name: "会话历史" }).click();
  await page.getByRole("button", { name: /Markdown 验收/ }).click();

  await expect(page.getByRole("heading", { name: "高风险异常汇总" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Markdown 表格" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "4" })).toBeVisible();
  await expect(page.getByRole("link", { name: "查看说明" })).toHaveAttribute("href", "https://example.com");
  await expect(page.getByText("[图片：远程图片]", { exact: true })).toBeVisible();
  await expect(page.locator("script").filter({ hasText: "window.__unsafeMarkdown" })).toHaveCount(0);
  await expect(page.getByText(/window\.__unsafeMarkdown/)).toHaveCount(0);
  expect(await page.evaluate(() => (window as Window & { __unsafeMarkdown?: boolean }).__unsafeMarkdown)).toBeUndefined();
  await page.screenshot({ path: testInfo.outputPath("exception-ai-markdown.png") });
});

test("case answer opens supplement form and completes one-confirmation remediation", async ({ page }) => {
  const workflowBase = {
    workflow_no: "AI-REMED-E2E-1",
    case_no: "EXC-REMED-E2E-1",
    source_message_no: "AI-MSG-REMED-E2E-1",
    evidence_version: "evidence-v1",
    status: "form_ready",
    lock_version: 2,
    form_schema: {
      schema_version: "remediation-form.v1",
      title: "补充异常修复信息",
      reason: "需要核对来源文件",
      fields: [{ field_id: "note", field_type: "long_text", label: "核查结果", description: "填写人工核查结论", required: true, options: [], reference_type: null, min_value: null, max_value: null, max_length: 500 }],
      missing_evidence: [],
      generation_notes: [],
    },
    answers: {},
    plan: null,
    sandbox: {},
    result: {},
    error_code: null,
    attachments: [],
    can_execute: false,
    created_at: "2026-09-02T00:00:00Z",
    updated_at: "2026-09-02T00:00:00Z",
    completed_at: null,
  };
  const plan = {
    schema_version: "remediation-plan.v1",
    summary: "重新校验来源批次",
    confirmed_facts: ["来源文件已核对"],
    assumptions: [],
    steps: ["重新校验导入批次"],
    expected_impact: "刷新异常结果",
    verification_steps: ["复检案件"],
    rollback: "保留原始导入文件",
    risks: ["执行期间不要重复导入"],
    missing_information: [],
    action_candidate: { action_type: "revalidate_import_batch", parameters: { batch_id: 17 }, rationale: "规则匹配" },
    sandbox_candidate: null,
  };
  let savedAnswers: Record<string, unknown> | null = null;
  let confirmation: Record<string, unknown> | null = null;
  await mockApplication(page, ["exception_center.view", "crm_insight.view"]);
  await page.route("**/api/v1/ai/chat/conversations", (route) => fulfillJson(route, [{ conversation_no: "AI-CHAT-REMED", channel: "exception_center_web", status: "active", title: "案件 EXC-REMED-E2E-1", model_name: "GLM-5.2", message_count: 2, last_message: "完成分析", context_type: "exception_case", context_id: "EXC-REMED-E2E-1", operation: "exception.case_analysis", evidence_version: "evidence-v1", created_at: "2026-09-02T00:00:00Z", updated_at: "2026-09-02T00:01:00Z" }]));
  await page.route("**/api/v1/ai/chat/conversations/AI-CHAT-REMED/messages", (route) => fulfillJson(route, [
    { message_no: "AI-MSG-USER-E2E-1", sequence_no: 1, role: "user", content: "分析异常", status: "completed", source_refs: [], context_meta: { case_no: "EXC-REMED-E2E-1", evidence_version: "evidence-v1" }, artifacts: [], created_at: "2026-09-02T00:00:00Z" },
    { message_no: "AI-MSG-REMED-E2E-1", sequence_no: 2, role: "assistant", content: "## 结论摘要\n需要补充来源核查信息。", status: "completed", source_refs: [], context_meta: { case_no: "EXC-REMED-E2E-1", title: "导入批次异常", severity: "high", status: "open", evidence_version: "evidence-v1" }, artifacts: [{ type: "exception_case_analysis", case: { case_no: "EXC-REMED-E2E-1" }, available_actions: ["revalidate_import_batch"], remediation_enabled: true }], created_at: "2026-09-02T00:01:00Z" },
  ]));
  await page.route("**/api/v1/ai/remediations", (route) => fulfillJson(route, workflowBase, 201));
  await page.route("**/api/v1/ai/remediations/AI-REMED-E2E-1/answers", async (route) => {
    savedAnswers = route.request().postDataJSON();
    await fulfillJson(route, { ...workflowBase, status: "collecting", lock_version: 3, answers: { note: "已核对来源文件" } });
  });
  await page.route("**/api/v1/ai/remediations/AI-REMED-E2E-1/plan", (route) => fulfillJson(route, { ...workflowBase, status: "plan_ready", lock_version: 4, answers: { note: "已核对来源文件" }, plan, can_execute: true }));
  await page.route("**/api/v1/ai/remediations/AI-REMED-E2E-1/confirm-execute", async (route) => {
    confirmation = route.request().postDataJSON();
    await fulfillJson(route, { ...workflowBase, status: "completed", lock_version: 5, answers: { note: "已核对来源文件" }, plan, result: { mode: "controlled_action", action_no: "EXACT-E2E-1", status: "completed", verification: { passed: true } }, completed_at: "2026-09-02T00:03:00Z" });
  });

  await goToRoute(page, "/exceptions?assistant=open");
  await page.getByRole("button", { name: "会话历史" }).click();
  await page.getByRole("button", { name: /案件 EXC-REMED-E2E-1/ }).click();
  await page.getByRole("button", { name: "补充信息" }).click();
  await expect(page.getByTestId("exception-ai-remediation")).toBeVisible();
  await page.getByLabel("核查结果*").fill("已核对来源文件");
  await page.getByRole("button", { name: "生成修复方案" }).click();
  await expect(page.getByRole("heading", { name: "修复方案" })).toBeVisible();
  await page.getByText("我已核对修复范围、影响和回滚方式").click();
  await page.getByRole("button", { name: "确认并执行" }).click();
  await expect(page.getByRole("heading", { name: "受控修复已完成" })).toBeVisible();
  expect(savedAnswers).toMatchObject({ expected_lock_version: 2, answers: { note: "已核对来源文件" } });
  expect(confirmation).toMatchObject({ expected_lock_version: 4, confirmation: true });
  expect(String(confirmation?.idempotency_key)).toMatch(/^remediation:/);
});

test("chat supports history, new conversation and stop generation", async ({ page }) => {
  await mockApplication(page, ["exception_center.view", "crm_insight.view"]);
  await page.route("**/api/v1/ai/chat/conversations", (route) => fulfillJson(route, [{ conversation_no: "AI-CHAT-HISTORY", channel: "exception_center_web", status: "active", title: "历史异常分析", model_name: "GLM-5.2", message_count: 2, last_message: "历史结论", created_at: "2026-08-30T00:00:00Z", updated_at: "2026-08-30T00:01:00Z" }]));
  await page.route("**/api/v1/ai/chat/conversations/AI-CHAT-HISTORY/messages", (route) => fulfillJson(route, [{ message_no: "M1", sequence_no: 1, role: "user", content: "历史问题", status: "completed", source_refs: [], created_at: "2026-08-30T00:00:00Z" }, { message_no: "M2", sequence_no: 2, role: "assistant", content: "历史结论", status: "completed", source_refs: [], created_at: "2026-08-30T00:01:00Z" }]));
  await page.addInitScript(() => {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (!url.endsWith("/api/v1/ai/chat/streams")) return nativeFetch(input, init);
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode('event: run_started\ndata: {"run_no":"AI-RUN-STOP","conversation_no":"AI-CHAT-STOP","request_id":"REQ-STOP"}\n\n'));
          controller.enqueue(encoder.encode('event: delta\ndata: {"text":"正在生成"}\n\n'));
          init?.signal?.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")), { once: true });
        },
        cancel() {}
      });
      return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
    };
  });
  await goToRoute(page, "/exceptions?assistant=open");
  await page.getByRole("button", { name: "会话历史" }).click();
  await page.getByRole("button", { name: /历史异常分析/ }).click();
  await expect(page.getByText("历史结论", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "新建会话" }).click();
  await expect(page.getByText("今天需要先处理什么？", { exact: true })).toBeVisible();
  await page.getByPlaceholder("询问异常原因、风险或下一步动作").fill("测试停止生成");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("正在生成", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "停止" }).click();
  await expect(page.getByText("已停止生成", { exact: true })).toBeVisible();
});

test("controlled CRM proposal requires explicit confirmation and submits CAS plus idempotency", async ({ page }) => {
  let submitted: Record<string, unknown> | null = null;
  await mockApplication(page, ["exception_center.view", "exception_center.action_execute", "inventory_check.upload", "crm_insight.view", "crm_insight.review"]);
  await page.route("**/api/v1/ai/actions/proposals/AI-CRM-PROP-11/crm-review", async (route) => {
    submitted = route.request().postDataJSON();
    await fulfillJson(route, { execution_no: "AI-CRM-EXEC-11", proposal_no: "AI-CRM-PROP-11", status: "completed", idempotency_key: "server-redacted", attempts: 1, result: {}, verification: { human_confirmed: true }, completed_at: "2026-08-30T00:01:00Z" });
  });
  page.on("dialog", (dialog) => dialog.accept());
  await goToRoute(page, "/exceptions?view=actions");

  await expect(page.getByTestId("controlled-action-center")).toBeVisible();
  await page.getByRole("button", { name: "人工复核" }).click();
  await expect(page.getByTestId("controlled-action-confirmation")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认复核" })).toBeDisabled();
  await page.getByTestId("controlled-action-confirm").check();
  await page.getByRole("button", { name: "确认复核" }).click();

  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted).toMatchObject({ expected_updated_at: "2026-08-30T00:00:00Z", confirmation: true, decision: "accept" });
  expect(String(submitted?.idempotency_key)).toMatch(/^web-ai-action:/);
  await expect(page.getByText("AI-CRM-EXEC-11", { exact: false })).toBeVisible();
});

test("high-risk action keeps validation token ephemeral and executes only after confirmation", async ({ page }) => {
  let submitted: Record<string, unknown> | null = null;
  const validatedProposal = { id: 21, proposal_no: "AI-EXC-PROP-21", domain: "inventory", action_type: "rebuild_inventory_flow", resource_type: "exception_case", resource_id: "EXC-20260830-21", status: "validated", review_status: "pending", risk_level: "high", requires_confirmation: true, parameters: {}, impact: { affected_rows: 1 }, source_refs: [], executable: true, blockers: [], created_at: "2026-08-30T00:00:00Z", updated_at: "2026-08-30T00:02:00Z", reviewed_at: null };
  await mockApplication(page, ["exception_center.view", "exception_center.action_execute", "inventory_check.upload"]);
  await page.route("**/api/v1/ai/actions/exceptions/EXC-20260830-21/validate", (route) => fulfillJson(route, { proposal: validatedProposal, validation_token: "ephemeral-validation-token-123456", validation_expires_at: "2026-08-30T00:12:00Z" }));
  await page.route("**/api/v1/ai/actions/proposals/AI-EXC-PROP-21/execute", async (route) => {
    submitted = route.request().postDataJSON();
    await fulfillJson(route, { execution_no: "AI-EXC-EXEC-21", proposal_no: "AI-EXC-PROP-21", status: "completed", idempotency_key: "server-redacted", attempts: 1, result: {}, verification: { human_confirmed: true }, completed_at: "2026-08-30T00:03:00Z" });
  });
  page.on("dialog", (dialog) => dialog.accept());
  await goToRoute(page, "/exceptions?view=actions");

  await page.getByTestId("controlled-action-case-no").fill("EXC-20260830-21");
  await page.getByRole("button", { name: "校验影响" }).click();
  await expect(page.getByTestId("controlled-action-validation-ready")).toBeVisible();
  await expect(page.getByText("ephemeral-validation-token-123456", { exact: false })).toHaveCount(0);
  await page.getByTestId("controlled-action-confirm").check();
  await page.getByRole("button", { name: "确认执行" }).click();

  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted).toMatchObject({ expected_updated_at: "2026-08-30T00:02:00Z", confirmation: true, validation_token: "ephemeral-validation-token-123456" });
  expect(String(submitted?.idempotency_key)).toMatch(/^web-ai-action:/);
  await expect(page.getByText("AI-EXC-EXEC-21", { exact: false })).toBeVisible();
});

test("permission-scoped exception viewer cannot see AI or controlled action tabs", async ({ page }) => {
  await mockApplication(page, ["exception_center.view"]);
  await goToRoute(page, "/exceptions?view=ai");

  await expect(page.getByRole("button", { name: "异常案件" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("button", { name: "AI 协同" })).toHaveCount(0);
  await expect(page.getByTestId("exception-ai-chat-overlay")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "受控动作" })).toHaveCount(0);
  await expect(page).toHaveURL(/\/exceptions$/);
});
