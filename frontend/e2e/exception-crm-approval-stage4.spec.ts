import { expect, test, type Page, type Route } from "@playwright/test";

const now = "2026-07-29T08:00:00Z";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body)
  });
}

async function installBaseRoutes(page: Page, permissions: string[]) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, {
        id: 18,
        username: "stage4-operator",
        real_name: "第四阶段验收员",
        role: "admin",
        is_active: true,
        status: "active"
      });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, permissions);
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
    await route.fallback();
  });
}

async function openAppPath(page: Page, path: string) {
  await page.goto("index.html");
  await page.evaluate((nextPath) => {
    window.history.replaceState(null, "", nextPath);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
}

function taskRow(id: number) {
  return {
    id,
    project_id: 77,
    task_code: `TASK-${id}`,
    customer_code: "KH-STAGE4",
    customer_name_snapshot: "跨页任务客户",
    executor_user_id: 18,
    executor_name_snapshot: "第四阶段验收员",
    business_issue_point: "当前页列表不包含该任务",
    round_target: "验证异常深链精确打开",
    feedback_due_at: "2026-07-31T10:00:00Z",
    status: "active",
    minimum_action_done: false,
    need_support: false,
    need_manager_support: false,
    need_boss_decision: false,
    is_blocked: false,
    is_closed: false,
    project_purpose: "验证异常案件与 CRM 原记录闭环",
    created_at: now,
    updated_at: now
  };
}

function followupRow(id: number) {
  return {
    id,
    followup_no: `FU-${id}`,
    project_id: 77,
    task_id: 501,
    customer_code: "KH-STAGE4",
    customer_name: "跨页跟进客户",
    project_name: "异常治理联调项目",
    executor_user_id: 18,
    executor_name_snapshot: "第四阶段验收员",
    followup_date: "2026-07-29",
    method: "电话",
    frontline_action: "复核异常证据",
    customer_feedback: "同意补充业务记录",
    current_need: "定位原始跟进记录",
    next_action: "完成复检",
    minimum_action_done: true,
    business_profile_updated: false,
    customer_profile_updated: false,
    need_support: false,
    need_manager_support: false,
    need_boss_decision: false,
    is_closed: false,
    valid_feedback: true,
    review_status: "approved",
    created_at: now,
    updated_at: now
  };
}

function approvalRow(id: number) {
  return {
    id,
    approval_no: `AP-${id}`,
    approval_type: "crm_followup_submit",
    resource_type: "crm_followup",
    resource_id: "601",
    title: "跨页审批详情",
    description: "该审批不在当前审批列表页中",
    applicant_user_id: 18,
    applicant_user_label: "第四阶段验收员",
    current_handler_user_id: 18,
    current_handler_user_label: "第四阶段验收员",
    status: "submitted",
    priority: "normal",
    payload_json: { followup: followupRow(601) },
    business_summary: { customer_name: "跨页审批客户", followup: followupRow(601) },
    created_at: now,
    updated_at: now
  };
}

function taskDetail(id: number) {
  return {
    task: taskRow(id),
    project: {
      id: 77,
      project_code: "PRJ-STAGE4",
      project_name: "异常治理联调项目",
      purpose: "验证异常案件与 CRM 原记录闭环",
      status: "active",
      approval_status: "approved",
      created_at: now,
      updated_at: now
    },
    followups: [],
    approvals: [],
    work_items: []
  };
}

function exceptionSummary(domain: "crm" | "approval") {
  return {
    total: 1,
    open: 1,
    action_required: 0,
    processing: 0,
    blocked: 0,
    resolved: 0,
    ignored: 0,
    unread_notifications: 0,
    ai_enabled: true,
    actions_enabled: false,
    by_domain: { [domain]: 1 },
    by_severity: { high: 1 },
    by_occurrence: { new: 1 }
  };
}

function exceptionPolicyPayload(
  domainModes: { crm: "off" | "shadow" | "visible"; approval: "off" | "shadow" | "visible" } = { crm: "off", approval: "off" },
  updatedAt = now
) {
  return {
    policy_key: "default",
    is_enabled: true,
    manual_ai_enabled: true,
    scheduled_ai_enabled: false,
    full_scan_enabled: false,
    digest_enabled: false,
    full_scan_cron: "30 2 * * *",
    digest_cron: "30 8 * * *",
    ai_daily_limit: 100,
    ai_batch_limit: 50,
    manual_ai_daily_limit: 20,
    scheduled_ai_daily_limit: 80,
    scheduled_ai_batch_limit: 50,
    ai_concurrency: 2,
    stale_diagnosis_hours: 24,
    domain_modes: domainModes,
    settings: {},
    updated_at: updatedAt
  };
}

function emptyDiagnosisQuality() {
  return {
    generated_at: now,
    total_diagnoses: 0,
    feedback_count: 0,
    by_feedback: {},
    by_disposition: {},
    by_root_cause_code: [],
    by_contract_version: [],
    by_domain: [],
    by_rule: [],
    by_model: [],
    by_prompt_version: [],
    rules: [],
    usage_reported_count: 0,
    usage_missing_count: 0
  };
}

test("task deep link fetches the exact record and close preserves list context", async ({ page }) => {
  let detailRequests = 0;
  await installBaseRoutes(page, ["crm_task.view", "crm_project.view"]);
  await page.route("**/api/v1/crm/tasks/page**", (route) => fulfillJson(route, {
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
    submission_summary: { total: 0, submitted: 0, unsubmitted: 0, needs_action: 0 }
  }));
  await page.route("**/api/v1/crm/tasks/501", async (route) => {
    detailRequests += 1;
    await fulfillJson(route, taskDetail(501));
  });

  await openAppPath(page, "/crm/tasks?task_id=501&q=%E8%B7%A8%E9%A1%B5&scope=open&return_case=EXC-CRM-501");

  const drawer = page.getByRole("dialog", { name: "任务明细" });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("跨页任务客户");
  await expect(drawer).toContainText("TASK-501");
  await expect.poll(() => detailRequests).toBeGreaterThan(0);

  await drawer.getByRole("button", { name: "关闭" }).click();
  await expect(drawer).toHaveCount(0);
  await expect.poll(() => {
    const url = new URL(page.url());
    return {
      taskId: url.searchParams.get("task_id"),
      query: url.searchParams.get("q"),
      scope: url.searchParams.get("scope"),
      returnCase: url.searchParams.get("return_case")
    };
  }).toEqual({ taskId: null, query: "跨页", scope: "open", returnCase: "EXC-CRM-501" });
});

test("same-path popstate opens the newly requested task instead of stale drawer state", async ({ page }) => {
  const detailRequests: number[] = [];
  await installBaseRoutes(page, ["crm_task.view", "crm_project.view"]);
  await page.route("**/api/v1/crm/tasks/page**", (route) => fulfillJson(route, {
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
    submission_summary: { total: 0, submitted: 0, unsubmitted: 0, needs_action: 0 }
  }));
  for (const taskId of [501, 502]) {
    await page.route(`**/api/v1/crm/tasks/${taskId}`, async (route) => {
      detailRequests.push(taskId);
      await fulfillJson(route, taskDetail(taskId));
    });
  }

  await openAppPath(page, "/crm/tasks?task_id=501&q=first");
  await expect(page.getByRole("dialog", { name: "任务明细" })).toContainText("TASK-501");

  await page.evaluate(() => {
    window.history.replaceState(null, "", "/crm/tasks?task_id=502&q=second");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  const drawer = page.getByRole("dialog", { name: "任务明细" });
  await expect(drawer).toContainText("TASK-502");
  await expect(drawer).not.toContainText("TASK-501");
  await expect.poll(() => detailRequests).toEqual([501, 502]);
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("second");
});

test("follow-up deep link fetches the exact record and close preserves filters", async ({ page }) => {
  let detailRequests = 0;
  await installBaseRoutes(page, ["crm_followup.view", "crm_project.view"]);
  await page.route("**/api/v1/crm/followups/page**", (route) => fulfillJson(route, { items: [], total: 0, limit: 20, offset: 0 }));
  await page.route("**/api/v1/crm/followups/601", async (route) => {
    detailRequests += 1;
    await fulfillJson(route, followupRow(601));
  });

  await openAppPath(page, "/crm/followups?followup_id=601&review_status=approved&customer_code=KH-STAGE4&return_case=EXC-CRM-601");

  const drawer = page.getByRole("dialog", { name: "跟进记录 FU-601" });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("跨页跟进客户");
  await expect(drawer).toContainText("同意补充业务记录");
  await expect.poll(() => detailRequests).toBeGreaterThan(0);

  await drawer.getByRole("button", { name: "关闭" }).click();
  await expect.poll(() => {
    const url = new URL(page.url());
    return {
      followupId: url.searchParams.get("followup_id"),
      reviewStatus: url.searchParams.get("review_status"),
      customerCode: url.searchParams.get("customer_code"),
      returnCase: url.searchParams.get("return_case")
    };
  }).toEqual({ followupId: null, reviewStatus: "approved", customerCode: "KH-STAGE4", returnCase: "EXC-CRM-601" });
});

test("approval deep link opens outside the current queue and close keeps execution view", async ({ page }) => {
  let detailRequests = 0;
  await installBaseRoutes(page, ["approval.view"]);
  await page.route("**/api/v1/approvals/page**", (route) => fulfillJson(route, { items: [], total: 0, limit: 12, offset: 0 }));
  await page.route("**/api/v1/approvals/701", async (route) => {
    detailRequests += 1;
    await fulfillJson(route, { approval: approvalRow(701), events: [], attachments: [] });
  });

  await openAppPath(page, "/crm/work?view=approvals&approval_id=701&approval_status=submitted&return_case=EXC-APPROVAL-701");

  const drawer = page.getByRole("dialog", { name: "审批详情" });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("AP-701");
  await expect(drawer).toContainText("跨页审批详情");
  await expect.poll(() => detailRequests).toBeGreaterThan(0);

  await drawer.getByRole("button", { name: "关闭" }).click();
  await expect.poll(() => {
    const url = new URL(page.url());
    return {
      approvalId: url.searchParams.get("approval_id"),
      view: url.searchParams.get("view"),
      approvalStatus: url.searchParams.get("approval_status"),
      returnCase: url.searchParams.get("return_case")
    };
  }).toEqual({ approvalId: null, view: "approvals", approvalStatus: "submitted", returnCase: "EXC-APPROVAL-701" });
});

test("unsupported CRM cases explain deterministic coverage and never expose AI diagnosis or retry", async ({ page }) => {
  const caseNo = "EXC-CRM-UNSUPPORTED-1";
  let diagnosisRequests = 0;
  const crmCase = {
    id: 81,
    case_no: caseNo,
    domain: "crm",
    rule_code: "crm.task_close_state_mismatch",
    title: "CRM 任务关闭状态不一致",
    severity: "high",
    status: "open",
    diagnosis_supported: false,
    occurrence_type: "new",
    resource_type: "crm_project_task",
    resource_id: "501",
    resource_code: "TASK-501",
    resource_name: "KH-STAGE4",
    source_type: "crm_project_task",
    source_id: "501",
    data_date: "2026-07-29",
    evidence_version: "crm-evidence-v1",
    reason: "任务状态为 closed，但关闭标记为否。",
    initial_guidance: "核对任务关闭动作及状态同步逻辑，修正后重新执行确定性复检。",
    action_path: "/crm/tasks?task_id=501",
    affected_rows: 1,
    detected_at: now,
    last_seen_at: now,
    metadata: {}
  };

  await installBaseRoutes(page, ["exception_center.view", "exception_center.diagnose", "exception_center.policy_manage", "crm_task.view"]);
  await page.route("**/api/v1/exception-notifications", (route) => fulfillJson(route, []));
  await page.route("**/api/v1/exceptions/summary", (route) => fulfillJson(route, exceptionSummary("crm")));
  await page.route("**/api/v1/exceptions/page**", (route) => fulfillJson(route, { items: [crmCase], total: 1, limit: 30, offset: 0 }));
  await page.route(`**/api/v1/exceptions/${caseNo}`, (route) => fulfillJson(route, {
    ...crmCase,
    evidence: {
      kind: "crm_task_close_state",
      task_id: 501,
      task_code: "TASK-501",
      project_id: 77,
      customer_code: "KH-STAGE4",
      status: "closed",
      is_closed: false,
      updated_at: now
    },
    diagnoses: [],
    actions: [],
    events: [],
    active_diagnosis_job: {
      id: 901,
      job_no: "EXJ-HISTORICAL-901",
      case_no: caseNo,
      evidence_version: "crm-evidence-v1",
      trigger_type: "manual",
      status: "failed",
      reused: false,
      attempts: 1,
      attempt_count: 1,
      retryable: true,
      cancellable: false,
      error_message: "历史任务在业务域关闭前失败",
      created_at: now,
      completed_at: now
    }
  }));
  await page.route(`**/api/v1/exceptions/${caseNo}/diagnoses`, async (route) => {
    diagnosisRequests += 1;
    await fulfillJson(route, { detail: "must not be called" }, 500);
  });

  await openAppPath(page, "/exceptions");
  await page.getByText("CRM 任务关闭状态不一致", { exact: true }).click();

  const drawer = page.getByRole("dialog", { name: /CRM 任务关闭状态不一致/ });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByTestId("exception-diagnose")).toHaveCount(0);
  await expect(drawer.getByTestId("exception-active-job")).toContainText("EXJ-HISTORICAL-901");
  await expect(drawer.getByTestId("exception-job-retry")).toHaveCount(0);
  await expect(drawer.getByRole("button", { name: "重试任务" })).toHaveCount(0);
  await expect(drawer).toContainText(/确定性规则|确定性校验/);
  await expect(drawer).toContainText(/暂不支持.*智能诊断|智能诊断.*暂不支持/);
  const evidence = drawer.getByTestId("exception-business-evidence-crm");
  await expect(evidence).toContainText("TASK-501");
  await expect(evidence).toContainText("关闭标记");
  await expect(evidence).toContainText("否");
  await expect.poll(() => diagnosisRequests).toBe(0);
});

test("source-record round trip preserves context and reopens the exact exception case", async ({ page }) => {
  const caseNo = "EXC-CRM-ROUNDTRIP-501";
  const crmCase = {
    id: 82,
    case_no: caseNo,
    domain: "crm",
    rule_code: "crm.task_close_state_mismatch",
    title: "CRM 任务关闭状态不一致",
    severity: "high",
    status: "open",
    diagnosis_supported: false,
    occurrence_type: "new",
    resource_type: "crm_project_task",
    resource_id: "501",
    resource_code: "TASK-501",
    resource_name: "KH-STAGE4",
    source_type: "crm_project_task",
    source_id: "501",
    data_date: "2026-07-29",
    evidence_version: "crm-roundtrip-v1",
    reason: "任务状态为 closed，但关闭标记为否。",
    initial_guidance: "打开任务明细核对关闭状态。",
    action_path: "/crm/tasks?task_id=501",
    affected_rows: 1,
    detected_at: now,
    last_seen_at: now,
    metadata: {}
  };

  await installBaseRoutes(page, ["exception_center.view", "crm_task.view", "crm_project.view"]);
  await page.route("**/api/v1/exception-notifications", (route) => fulfillJson(route, []));
  await page.route("**/api/v1/exceptions/summary", (route) => fulfillJson(route, exceptionSummary("crm")));
  await page.route("**/api/v1/exceptions/page**", (route) => fulfillJson(route, { items: [crmCase], total: 1, limit: 30, offset: 0 }));
  await page.route(`**/api/v1/exceptions/${caseNo}`, (route) => fulfillJson(route, {
    ...crmCase,
    evidence: {
      kind: "crm_task_close_state",
      task_id: 501,
      task_code: "TASK-501",
      project_id: 77,
      customer_code: "KH-STAGE4",
      status: "closed",
      is_closed: false,
      updated_at: now
    },
    diagnoses: [],
    actions: [],
    events: []
  }));
  await page.route("**/api/v1/crm/tasks/page**", (route) => fulfillJson(route, {
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
    submission_summary: { total: 0, submitted: 0, unsubmitted: 0, needs_action: 0 }
  }));
  await page.route("**/api/v1/crm/tasks/501", (route) => fulfillJson(route, taskDetail(501)));

  await openAppPath(page, `/exceptions?open=${caseNo}`);
  let exceptionDrawer = page.getByRole("dialog", { name: /CRM 任务关闭状态不一致/ });
  await expect(exceptionDrawer).toBeVisible();
  await exceptionDrawer.getByRole("button", { name: "定位原始记录" }).click();

  const taskDrawer = page.getByRole("dialog", { name: "任务明细" });
  await expect(taskDrawer).toBeVisible();
  await expect(taskDrawer).toContainText("TASK-501");
  await expect.poll(() => {
    const url = new URL(page.url());
    return {
      pathname: url.pathname,
      taskId: url.searchParams.get("task_id"),
      returnTo: url.searchParams.get("return_to"),
      returnCase: url.searchParams.get("return_case")
    };
  }).toEqual({
    pathname: "/crm/tasks",
    taskId: "501",
    returnTo: `/exceptions?open=${caseNo}`,
    returnCase: caseNo
  });

  await taskDrawer.getByRole("button", { name: "关闭" }).click();
  await expect(taskDrawer).toHaveCount(0);
  await expect.poll(() => {
    const url = new URL(page.url());
    return {
      taskId: url.searchParams.get("task_id"),
      returnTo: url.searchParams.get("return_to"),
      returnCase: url.searchParams.get("return_case")
    };
  }).toEqual({ taskId: null, returnTo: `/exceptions?open=${caseNo}`, returnCase: caseNo });

  await page.getByRole("button", { name: "返回异常案件" }).click();
  await expect.poll(() => {
    const url = new URL(page.url());
    return { pathname: url.pathname, open: url.searchParams.get("open") };
  }).toEqual({ pathname: "/exceptions", open: caseNo });
  exceptionDrawer = page.getByRole("dialog", { name: /CRM 任务关闭状态不一致/ });
  await expect(exceptionDrawer).toBeVisible();
  await expect(exceptionDrawer).toContainText(caseNo);
});

test("approval exception renders the terminal-integrity evidence contract", async ({ page }) => {
  const caseNo = "EXC-APPROVAL-EVIDENCE-701";
  const approvalCase = {
    id: 83,
    case_no: caseNo,
    domain: "approval",
    rule_code: "approval.terminal_integrity_mismatch",
    title: "审批终态完整性不一致",
    severity: "high",
    status: "open",
    diagnosis_supported: false,
    occurrence_type: "new",
    resource_type: "approval_instance",
    resource_id: "701",
    resource_code: "AP-701",
    resource_name: "crm_followup_submit",
    source_type: "approval_instance",
    source_id: "701",
    data_date: "2026-07-29",
    evidence_version: "approval-evidence-v1",
    reason: "审批已进入终态，但终态时间或最新状态事件不完整。",
    initial_guidance: "核对审批终态写入与状态事件，修正后重新执行确定性复检。",
    action_path: "/crm/work?view=approvals&approval_id=701",
    affected_rows: 1,
    detected_at: now,
    last_seen_at: now,
    metadata: {}
  };

  await installBaseRoutes(page, ["exception_center.view", "approval.view"]);
  await page.route("**/api/v1/exception-notifications", (route) => fulfillJson(route, []));
  await page.route("**/api/v1/exceptions/summary", (route) => fulfillJson(route, exceptionSummary("approval")));
  await page.route("**/api/v1/exceptions/page**", (route) => fulfillJson(route, { items: [approvalCase], total: 1, limit: 30, offset: 0 }));
  await page.route(`**/api/v1/exceptions/${caseNo}`, (route) => fulfillJson(route, {
    ...approvalCase,
    evidence: {
      kind: "approval_terminal_integrity",
      approval_id: 701,
      status: "rejected",
      reviewed_at: null,
      closed_at: null,
      latest_state_event_id: 991,
      latest_state_event_status: "approved",
      latest_state_event_at: now
    },
    diagnoses: [],
    actions: [],
    events: []
  }));

  await openAppPath(page, `/exceptions?open=${caseNo}`);
  const drawer = page.getByRole("dialog", { name: /审批终态完整性不一致/ });
  await expect(drawer).toBeVisible();
  const evidence = drawer.getByTestId("exception-business-evidence-approval");
  await expect(evidence).toContainText("审批记录");
  await expect(evidence).toContainText("审批 ID");
  await expect(evidence).toContainText("701");
  await expect(evidence).toContainText("审核时间未提供");
  await expect(evidence).toContainText("最新状态事件");
  await expect(evidence).toContainText("事件状态");
  await expect(evidence).toContainText("approved");
});

test("policy rollout saves shadow mode before establishing a versioned baseline", async ({ page }) => {
  const firstVersion = "2026-07-29T08:00:00Z";
  const shadowVersion = "2026-07-29T08:10:00Z";
  const baselineVersion = "2026-07-29T08:20:00Z";
  const visibleVersion = "2026-07-29T08:30:00Z";
  let policy = exceptionPolicyPayload({ crm: "off", approval: "off" }, firstVersion);
  const patches: Array<Record<string, unknown>> = [];
  const baselineRequests: Array<Record<string, unknown>> = [];

  await installBaseRoutes(page, ["exception_center.view", "exception_center.policy_manage"]);
  await page.route("**/api/v1/exception-notifications**", (route) => fulfillJson(route, []));
  await page.route("**/api/v1/exceptions/summary**", (route) => fulfillJson(route, exceptionSummary("crm")));
  await page.route("**/api/v1/exceptions/page**", (route) => fulfillJson(route, { items: [], total: 0, limit: 30, offset: 0 }));
  await page.route("**/api/v1/exception-policies", async (route) => {
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      patches.push(body);
      const nextModes = body.domain_modes as typeof policy.domain_modes | undefined;
      const nextVersion = nextModes?.crm === "visible" ? visibleVersion : shadowVersion;
      policy = { ...policy, ...(body as Partial<typeof policy>), updated_at: nextVersion };
    }
    await fulfillJson(route, policy);
  });
  await page.route("**/api/v1/exceptions/baseline-scan", async (route) => {
    baselineRequests.push(route.request().postDataJSON() as Record<string, unknown>);
    policy = { ...policy, updated_at: baselineVersion };
    await fulfillJson(route, {
      scan_reference: "baseline:crm:test-reference",
      audit_id: 901,
      domain: "crm",
      domain_mode: "shadow",
      shadow_cycle: 1,
      policy_updated_at: baselineVersion,
      reused: false,
      result: {
        domains: ["crm"],
        requested_domains: ["crm"],
        domain_modes: { crm: "shadow" },
        scan_trigger: "baseline",
        scanned: 18,
        created: 4,
        new: 0,
        reopened: 1,
        evidence_updated: 2,
        resolved: 1
      }
    });
  });

  await openAppPath(page, "/exceptions");
  await page.getByRole("button", { name: "巡检策略" }).click();
  const drawer = page.getByRole("dialog", { name: "异常巡检策略" });
  await expect(drawer).toBeVisible();
  const crm = drawer.getByTestId("exception-domain-mode-crm");
  const approval = drawer.getByTestId("exception-domain-mode-approval");
  await expect(crm.getByRole("button", { name: "建立基线" })).toBeDisabled();
  await expect(approval.getByRole("button", { name: "建立基线" })).toBeDisabled();

  await crm.getByRole("button", { name: "影子", exact: true }).click();
  await expect(crm.getByRole("button", { name: "建立基线" })).toBeDisabled();
  await drawer.getByRole("button", { name: "保存策略" }).click();
  await expect.poll(() => patches).toEqual([{
    domain_modes: { crm: "shadow", approval: "off" },
    expected_updated_at: firstVersion
  }]);

  await expect(crm.getByRole("button", { name: "建立基线" })).toBeEnabled();
  await crm.getByRole("button", { name: "建立基线" }).click();
  await expect.poll(() => baselineRequests).toEqual([{
    domain: "crm",
    expected_policy_updated_at: shadowVersion
  }]);
  await expect(crm.getByTestId("exception-baseline-result-crm")).toContainText("扫描 18 · 新建 4 · 新增 0 · 复发 1 · 证据更新 2 · 解决 1");

  await crm.getByRole("button", { name: "可见", exact: true }).click();
  const confirmation = drawer.getByTestId("exception-visible-confirmation");
  await expect(confirmation).toContainText("权限、重复案件、通知隔离和规则对账");
  await confirmation.getByRole("button", { name: "确认切换为可见" }).click();
  await drawer.getByRole("button", { name: "保存策略" }).click();
  await expect.poll(() => patches.length).toBe(2);
  expect(patches[1]).toEqual({
    domain_modes: { crm: "visible", approval: "off" },
    expected_updated_at: baselineVersion
  });
  await expect(crm.getByRole("button", { name: "建立基线" })).toBeDisabled();
  await expect(approval.getByRole("button", { name: "建立基线" })).toBeDisabled();
  expect(policy.updated_at).toBe(visibleVersion);
});

test("rule quality shows versions, lifecycle counts, and unavailable scan metrics", async ({ page }) => {
  const ruleQualityRequests: string[] = [];
  await installBaseRoutes(page, ["exception_center.view", "exception_center.policy_manage"]);
  await page.route("**/api/v1/exception-notifications**", (route) => fulfillJson(route, []));
  await page.route("**/api/v1/exceptions/summary**", (route) => fulfillJson(route, exceptionSummary("crm")));
  await page.route("**/api/v1/exceptions/page**", (route) => fulfillJson(route, { items: [], total: 0, limit: 30, offset: 0 }));
  await page.route("**/api/v1/exception-diagnoses/quality**", (route) => fulfillJson(route, emptyDiagnosisQuality()));
  await page.route("**/api/v1/exceptions/rule-quality**", async (route) => {
    const url = new URL(route.request().url());
    ruleQualityRequests.push(url.search);
    await fulfillJson(route, {
      generated_at: "2026-07-29T10:30:00Z",
      scan_job_window_days: 30,
      scan_job_window_start: "2026-06-29T10:30:00Z",
      scan_job_window_end: "2026-07-29T10:30:00Z",
      domains: [
        { domain: "crm", domain_mode: "shadow", total: 7, active: 4, baseline: 3, new: 3, reopened: 1, ignored: 0, resolved: 3, evidence_changed_events: 2, latest_seen_at: "2026-07-29T10:00:00Z", false_positive_rate: null, scan_job_metrics_available: true, queued_scan_jobs: 2, failed_scan_jobs: 1, scan_latency_p95_ms: 450 },
        { domain: "approval", domain_mode: "off", total: 5, active: 4, baseline: 1, new: 3, reopened: 1, ignored: 0, resolved: 1, evidence_changed_events: 4, latest_seen_at: null, false_positive_rate: null, scan_job_metrics_available: false, queued_scan_jobs: null, failed_scan_jobs: null, scan_latency_p95_ms: null }
      ],
      rules: [
        { domain: "crm", domain_mode: "shadow", rule_code: "crm.task_close_state_mismatch", rule_version: "2026.07.29-1", total: 5, active: 3, baseline: 2, new: 2, reopened: 1, ignored: 0, resolved: 2, evidence_changed_events: 2, latest_seen_at: "2026-07-29T10:00:00Z", false_positive_rate: null },
        { domain: "crm", domain_mode: "shadow", rule_code: "crm.followup_binding_mismatch", rule_version: "2026.07.29-2", total: 2, active: 1, baseline: 1, new: 1, reopened: 0, ignored: 0, resolved: 1, evidence_changed_events: 0, latest_seen_at: "2026-07-29T09:00:00Z", false_positive_rate: null },
        { domain: "approval", domain_mode: "off", rule_code: "approval.terminal_integrity_mismatch", rule_version: "2026.07.29-3", total: 5, active: 4, baseline: 1, new: 3, reopened: 1, ignored: 0, resolved: 1, evidence_changed_events: 4, latest_seen_at: null, false_positive_rate: null }
      ]
    });
  });

  await openAppPath(page, "/exceptions?view=quality");
  const quality = page.getByTestId("exception-rollout-rule-quality");
  await expect(quality).toBeVisible();
  await expect.poll(() => ruleQualityRequests).toEqual(["?scan_window_days=30"]);
  await expect(quality).toContainText("不是错误率或误报率指标");
  const crm = quality.getByTestId("exception-rollout-domain-crm");
  const approval = quality.getByTestId("exception-rollout-domain-approval");
  await expect(crm).toContainText(/规则数\s*2/);
  await expect(crm).toContainText(/活动案件\s*4/);
  await expect(crm).toContainText(/新增\s*3/);
  await expect(crm).toContainText(/复发\s*1/);
  await expect(crm).toContainText(/证据变化\s*2/);
  await expect(crm).toContainText("v2026.07.29-1");
  await expect(crm.getByTestId("exception-scan-metrics-crm")).toContainText("排队 2 · 失败 1 · P95 450 ms");
  await expect(approval).toContainText(/规则数\s*1/);
  await expect(approval).toContainText(/活动案件\s*4/);
  await expect(approval).toContainText(/证据变化\s*4/);
  await expect(approval).toContainText("v2026.07.29-3");
  await expect(approval.getByTestId("exception-scan-metrics-approval")).toContainText("指标不可用");
  await expect(approval.getByTestId("exception-scan-metrics-approval")).toContainText("排队 - · 失败 - · P95 -");
  await expect(quality.getByText(/误报率\s*\d/)).toHaveCount(0);
});

test("special approval role can open the exact approval detail", async ({ page }) => {
  const leadApproval = {
    ...approvalRow(701),
    approval_type: "crm_lead_convert",
    title: "客户开发转正审批",
    business_summary: { customer_name: "特殊审批角色客户" }
  };
  await installBaseRoutes(page, ["crm_lead.approve"]);
  await page.route("**/api/v1/approvals/page**", (route) => fulfillJson(route, { items: [], total: 0, limit: 12, offset: 0 }));
  await page.route("**/api/v1/approvals/701", (route) => fulfillJson(route, { approval: leadApproval, events: [], attachments: [] }));

  await openAppPath(page, "/crm/work?view=approvals&approval_id=701");
  const drawer = page.getByRole("dialog", { name: "审批详情" });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("客户开发转正审批");
  await expect(drawer.getByRole("button", { name: "审批通过" })).toBeVisible();
  await expect(page.getByText("当前 CRM 页面不可见")).toHaveCount(0);
});

test("applicant and current handler can open backend-authorized approval links without list permission", async ({ page }) => {
  let listRequests = 0;
  const applicantApproval = {
    ...approvalRow(702),
    title: "申请人授权审批详情",
    applicant_user_id: 18,
    current_handler_user_id: 99
  };
  const handlerApproval = {
    ...approvalRow(703),
    title: "当前处理人授权审批详情",
    applicant_user_id: 99,
    current_handler_user_id: 18
  };
  await installBaseRoutes(page, []);
  await page.route("**/api/v1/approvals/page**", async (route) => {
    listRequests += 1;
    await fulfillJson(route, { items: [], total: 0, limit: 12, offset: 0 });
  });
  await page.route("**/api/v1/approvals/702", (route) => fulfillJson(route, { approval: applicantApproval, events: [], attachments: [] }));
  await page.route("**/api/v1/approvals/703", (route) => fulfillJson(route, { approval: handlerApproval, events: [], attachments: [] }));

  await openAppPath(page, "/crm/work?view=approvals&approval_id=702");
  let drawer = page.getByRole("dialog", { name: "审批详情" });
  await expect(drawer).toContainText("申请人授权审批详情");
  await expect(drawer.getByRole("button", { name: "审批通过" })).toHaveCount(0);
  await drawer.getByRole("button", { name: "关闭" }).click();

  await page.evaluate(() => {
    window.history.pushState(null, "", "/crm/work?view=approvals&approval_id=703");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  drawer = page.getByRole("dialog", { name: "审批详情" });
  await expect(drawer).toContainText("当前处理人授权审批详情");
  await expect(drawer.getByRole("button", { name: "审批通过" })).toHaveCount(0);
  await expect.poll(() => listRequests).toBe(0);
  await expect(page.getByText("当前 CRM 页面不可见")).toHaveCount(0);
});
