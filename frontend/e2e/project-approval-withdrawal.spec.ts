import { expect, test, type Page, type Route } from "@playwright/test";

const now = "2026-08-08T08:00:00Z";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function openAppPath(page: Page, path: string) {
  await page.goto("index.html");
  await page.evaluate((nextPath) => {
    window.history.replaceState(null, "", nextPath);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
}

function projectApproval(status = "completed") {
  return {
    id: 901,
    approval_no: "AP-WITHDRAW-901",
    approval_type: "crm_project_create",
    resource_type: "crm_project",
    resource_id: "77",
    title: "重点客户项目申请",
    applicant_user_id: 21,
    applicant_user_label: "项目申请人",
    current_handler_user_id: 18,
    current_handler_user_label: "项目审批人",
    status,
    priority: "normal",
    payload_json: {
      project: { id: 77, project_name: "重点客户推进项目", purpose: "完成客户资料核验" },
      tasks: [{ customer_code: "KH001", customer_name: "验收客户", round_target: "完成首次沟通" }]
    },
    business_summary: {
      project: { id: 77, project_name: "重点客户推进项目", purpose: "完成客户资料核验" },
      tasks: [{ customer_code: "KH001", customer_name: "验收客户", round_target: "完成首次沟通" }],
      review_withdrawal: status === "need_supplement"
        ? {
            state: "withdrawn",
            can_withdraw: false,
            reason: "客户任务范围需要补充确认",
            withdrawn_at: now,
            withdrawn_by_user_label: "项目审批人"
          }
        : { state: "available", can_withdraw: true }
    },
    submitted_at: "2026-08-08T07:00:00Z",
    reviewed_at: status === "completed" ? now : null,
    closed_at: status === "completed" ? now : null,
    created_at: "2026-08-08T07:00:00Z",
    updated_at: now
  };
}

test("completed project approval previews impact and withdraws into frozen supplement state", async ({ page }) => {
  let approval = projectApproval();
  let submittedReason = "";

  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/auth/me") {
      await fulfillJson(route, { id: 18, username: "approver", real_name: "项目审批人", role: "admin", is_active: true, status: "active" });
      return;
    }
    if (url.pathname === "/api/v1/auth/my-permissions") {
      await fulfillJson(route, ["approval.view", "approval.approve", "crm_project.view", "crm_project.approval_withdraw", "crm_project.approval_withdraw_override"]);
      return;
    }
    if (url.pathname === "/api/v1/approvals/page") {
      await fulfillJson(route, { items: [], total: 0, limit: 12, offset: 0 });
      return;
    }
    if (url.pathname === "/api/v1/approvals/901/withdrawal-preview") {
      await fulfillJson(route, {
        approval_id: 901,
        project_id: 77,
        state: "available",
        can_withdraw: true,
        deadline: "2026-08-09T08:00:00Z",
        is_override: true,
        blockers: [],
        impact_counts: { tasks: 3, followups: 5, work_items: 2, pending_approvals: 1 },
        project_status: "active"
      });
      return;
    }
    if (url.pathname === "/api/v1/approvals/901/withdraw-approved") {
      submittedReason = String((await route.request().postDataJSON()).reason ?? "");
      approval = projectApproval("need_supplement");
      await fulfillJson(route, {
        approval,
        events: [{ id: 1, approval_id: 901, event_type: "withdraw_approved_project", operator_user_id: 18, operator_user_label: "项目审批人", from_status: "completed", to_status: "need_supplement", comment: submittedReason, created_at: now }],
        attachments: []
      });
      return;
    }
    if (url.pathname === "/api/v1/approvals/901") {
      await fulfillJson(route, { approval, events: [], attachments: [] });
      return;
    }
    if (url.pathname === "/api/v1/admin/stage1/summary") {
      await fulfillJson(route, {});
      return;
    }
    await fulfillJson(route, { items: [], total: 0, limit: 20, offset: 0 });
  });

  await openAppPath(page, "/crm/work?view=approvals&approval_id=901");

  const drawer = page.getByRole("dialog", { name: "审批详情" });
  await expect(drawer.getByTestId("project-approval-withdrawal-panel")).toContainText("管理员越权撤回");
  await drawer.getByRole("button", { name: "撤回审核" }).click();

  const dialog = page.getByRole("dialog", { name: "确认撤回已通过项目审核" });
  await expect(dialog).toContainText("任务");
  await expect(dialog).toContainText("3");
  await expect(dialog).toContainText("跟进");
  await expect(dialog).toContainText("5");
  await expect(dialog.getByRole("button", { name: "确认撤回并冻结项目" })).toBeDisabled();

  await dialog.getByLabel("撤回原因（必填，5–1000 字）").fill("客户任务范围需要补充确认");
  await dialog.getByRole("button", { name: "确认撤回并冻结项目" }).click();

  await expect(dialog).toBeHidden();
  await expect(drawer.getByTestId("project-approval-frozen-banner")).toContainText("客户任务范围需要补充确认");
  await expect(drawer).toContainText("审批人撤回已通过审核");
  expect(submittedReason).toBe("客户任务范围需要补充确认");
});
