export type InteractionObjectState =
  | "normal"
  | "draft"
  | "need_supplement"
  | "pending_approval"
  | "failed"
  | "high_risk";

export type InteractionResult =
  | "open_detail_drawer"
  | "open_edit_drawer"
  | "open_review_drawer"
  | "open_import_drawer"
  | "open_help_drawer"
  | "open_confirm_dialog"
  | "navigate_with_filter";

export type PageInteractionRule = {
  page: string;
  primaryGoal: string;
  primaryActionSlot: "header_right";
  rowClick: InteractionResult;
  secondaryActions: "kebab_menu" | "drawer_actions";
  rightRail: "page_action_assistant";
  emptyState: "single_recommended_action";
};

export const interactionResultLabels: Record<InteractionResult, string> = {
  open_detail_drawer: "打开详情抽屉",
  open_edit_drawer: "打开编辑抽屉",
  open_review_drawer: "打开审批处理抽屉",
  open_import_drawer: "打开导入抽屉",
  open_help_drawer: "打开说明抽屉",
  open_confirm_dialog: "打开二次确认",
  navigate_with_filter: "带筛选进入页面"
};

export const objectStateClickRules: Record<InteractionObjectState, InteractionResult> = {
  normal: "open_detail_drawer",
  draft: "open_edit_drawer",
  need_supplement: "open_edit_drawer",
  pending_approval: "open_review_drawer",
  failed: "open_detail_drawer",
  high_risk: "open_confirm_dialog"
};

export const globalInteractionRules = {
  primaryActionLimitPerPage: 1,
  maxSecondaryActionsPerGroup: 3,
  defaultPageSize: 50,
  rowClickDefault: "open_detail_drawer" satisfies InteractionResult,
  draftClickDefault: "open_edit_drawer" satisfies InteractionResult,
  dangerousActionDefault: "open_confirm_dialog" satisfies InteractionResult,
  helpActionDefault: "open_help_drawer" satisfies InteractionResult,
  rightRailDefault: "page_action_assistant" as const,
  hiddenInProductionCopy: [
    ["端", "口"].join(""),
    ["测", "试"].join(""),
    ["施", "工"].join(""),
    ["临", "时", "编", "号"].join(""),
    ["迁", "移", "细", "节"].join("")
  ]
};

export const pageInteractionRules: PageInteractionRule[] = [
  {
    page: "dashboard",
    primaryGoal: "查看今日经营状态、风险和待办",
    primaryActionSlot: "header_right",
    rowClick: "open_detail_drawer",
    secondaryActions: "drawer_actions",
    rightRail: "page_action_assistant",
    emptyState: "single_recommended_action"
  },
  {
    page: "master-data",
    primaryGoal: "查询主数据档案、查看详情、导入数据",
    primaryActionSlot: "header_right",
    rowClick: "open_detail_drawer",
    secondaryActions: "kebab_menu",
    rightRail: "page_action_assistant",
    emptyState: "single_recommended_action"
  },
  {
    page: "process-data",
    primaryGoal: "查看销售、库存、采购和往来过程数据",
    primaryActionSlot: "header_right",
    rowClick: "open_detail_drawer",
    secondaryActions: "kebab_menu",
    rightRail: "page_action_assistant",
    emptyState: "single_recommended_action"
  },
  {
    page: "image-tools",
    primaryGoal: "发起图片处理、查看任务和下载结果",
    primaryActionSlot: "header_right",
    rowClick: "open_detail_drawer",
    secondaryActions: "drawer_actions",
    rightRail: "page_action_assistant",
    emptyState: "single_recommended_action"
  },
  {
    page: "crm",
    primaryGoal: "按客户全景、业务执行、我的工作完成 CRM 闭环",
    primaryActionSlot: "header_right",
    rowClick: "open_detail_drawer",
    secondaryActions: "drawer_actions",
    rightRail: "page_action_assistant",
    emptyState: "single_recommended_action"
  },
  {
    page: "users",
    primaryGoal: "管理账号生命周期、角色模板和权限覆盖",
    primaryActionSlot: "header_right",
    rowClick: "open_detail_drawer",
    secondaryActions: "kebab_menu",
    rightRail: "page_action_assistant",
    emptyState: "single_recommended_action"
  },
  {
    page: "settings",
    primaryGoal: "查看服务健康、运行配置和系统审计",
    primaryActionSlot: "header_right",
    rowClick: "open_detail_drawer",
    secondaryActions: "drawer_actions",
    rightRail: "page_action_assistant",
    emptyState: "single_recommended_action"
  }
];

export const feedbackRules = {
  saveSuccess: "保存成功",
  submitSuccess: "提交成功",
  draftSaved: "草稿已保存，可在我的提交继续编辑",
  importSuccess: "导入完成",
  approvalDone: "审批处理完成",
  failureFallback: "操作失败，请检查表单内容后重试"
};

export function getInteractionResultForState(state: InteractionObjectState): InteractionResult {
  return objectStateClickRules[state];
}

export function getPageInteractionRule(page: string): PageInteractionRule | undefined {
  return pageInteractionRules.find((rule) => rule.page === page);
}
