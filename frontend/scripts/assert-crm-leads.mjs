import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd());
const app = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");
const client = fs.readFileSync(path.join(root, "src", "api", "client.ts"), "utf8");

function assertIncludes(source, needle, message) {
  if (!source.includes(needle)) throw new Error(message);
}

function assertNotIncludes(source, needle, message) {
  if (source.includes(needle)) throw new Error(message);
}

function assertCountAtLeast(source, needle, expected, message) {
  const count = source.split(needle).length - 1;
  if (count < expected) throw new Error(`${message}（实际 ${count}，预期至少 ${expected}）`);
}

assertIncludes(app, '| "leads"', "CRM 分区需要注册客户开发页面");
assertIncludes(app, 'path: "/crm/leads"', "客户开发必须使用 /crm/leads 路径");
assertIncludes(app, 'label: "客户开发"', "CRM 导航需要展示客户开发模块");
assertIncludes(app, 'permissions: ["crm_lead.view"]', "客户开发导航必须由 crm_lead.view 权限控制");
assertIncludes(app, '{ code: "crm-lead", label: "客户开发", resources: ["crm_lead"]', "角色模板权限矩阵必须包含客户开发子模块");
assertIncludes(app, 'permissionCodes: ["crm_lead.view", "crm_lead.create", "crm_lead.edit", "crm_lead.assign", "crm_lead.convert", "crm_lead.approve"]', "客户开发权限矩阵必须覆盖查看、新增、修改、分配、转正和审批");
assertIncludes(app, 'crm_lead: "客户开发线索"', "权限资源必须使用业务可读的客户开发名称");
assertIncludes(app, '"crm_lead.convert", "crm_lead.approve"', "客户转正与审批权限必须标记为高风险");
assertIncludes(app, '客户转正会创建正式客户档案', "客户开发高风险权限必须解释业务影响");
assertIncludes(app, 'hasPermission(permissions, "crm_lead.view")', "客户开发页面必须单独检查查看权限");
assertIncludes(app, 'type CrmLeadWorkspaceView = "mine" | "public-pool" | "sla" | "campaigns" | "analysis"', "客户开发需要提供线索、公共池、SLA、活动和分析视图");
assertIncludes(app, 'label: "我的线索"', "客户开发需要提供我的线索页签");
assertIncludes(app, 'label: "团队分析"', "客户开发需要提供团队分析页签");
assertIncludes(app, 'status_value: statusFilter === "followup_pending" ? "" : statusFilter', "待跟进组合筛选不能再发送单一状态值");
assertIncludes(app, 'status_group: statusFilter === "followup_pending" ? "followup_pending" : ""', "待跟进卡片必须请求后端组合状态筛选");
assertIncludes(app, 'source: sourceFilter,', "线索池请求必须固定发起时的来源筛选");
assertIncludes(app, 'region: regionFilter,', "线索池请求必须固定发起时的区域筛选");
assertIncludes(app, 'limit: pageSize,', "线索池请求必须固定发起时的分页大小");
assertIncludes(app, 'offset', "线索池请求必须固定发起时的分页位置");
assertIncludes(app, 'crmLeadsPage(requestScope, { signal: controller.signal })', "线索池必须走后端分页、搜索和筛选接口");
assertIncludes(app, 'const summaryTotalRows = pageData?.summary?.total ?? filteredTotalRows', "线索总数卡必须使用后端权限范围摘要");
assertIncludes(app, 'const statusSummary = pageData?.summary?.by_status ?? {}', "状态统计卡必须使用后端完整状态摘要");
assertIncludes(app, 'detail={`待接触 ${pendingDraftRows} · 推进中 ${pendingActiveRows}`}', "待跟进卡必须分别展示待接触和推进中数量");
assertNotIncludes(app, 'value={pageRows.filter((lead)', "线索统计卡不能使用当前分页数据计算数量");
assertIncludes(app, 'const applyLeadMetricFilter = (nextStatus: "" | "followup_pending" | "conversion_pending" | "converted")', "线索统计卡必须复用统一筛选入口");
assertIncludes(app, 'active={statusFilter === "followup_pending"}', "待跟进统计卡必须展示选中状态");
assertIncludes(app, 'onClick={() => applyLeadMetricFilter("followup_pending")}', "待跟进统计卡必须支持点击筛选和再次点击取消");
assertIncludes(app, '{ value: "followup_pending", label: "待跟进（待接触+推进中）" }', "阶段下拉必须同步展示待跟进组合筛选");
assertIncludes(app, 'active={statusFilter === "conversion_pending"}', "转正审批统计卡必须展示选中状态");
assertIncludes(app, 'active={statusFilter === "converted"}', "已转正统计卡必须展示选中状态");
assertIncludes(app, 'leadPoolRequestRef', "线索池请求必须持有当前筛选、查询和分页代次");
assertIncludes(app, 'controller?.abort();', "发起新的线索池请求前必须取消上一代请求");
assertIncludes(app, '{ signal: controller.signal }', "线索池请求必须传递取消信号");
assertCountAtLeast(app, 'leadPoolRequestRef.current.generation !== generation', 2, "过期线索池请求的成功和失败都不能改写当前界面");
assertIncludes(app, 'controller.signal.aborted', "已取消线索池请求不能显示为加载失败");
assertIncludes(app, 'useEffect(() => () => leadPoolRequestRef.current.controller?.abort(), [])', "线索池离开页面时必须取消在途请求");
assertIncludes(app, 'leadDetailRequestRef', "线索详情请求必须持有当前抽屉请求代次和线索标识");
assertIncludes(app, 'selectedLeadId: number | null', "线索详情请求必须按当前选中线索标识隔离");
assertIncludes(app, 'leadDetailRequestRef.current.controller?.abort();', "切换线索或刷新详情前必须取消上一条详情请求");
assertIncludes(app, 'crmLeadDetail(lead.id, { signal: controller.signal })', "线索详情请求必须传递取消信号");
assertCountAtLeast(app, 'isActiveLeadDetailRequest(generation, lead.id)', 4, "过期线索详情请求的成功、审批结果、失败和加载状态都不能改写当前抽屉");
assertIncludes(app, 'useEffect(() => () => cancelLeadDetailRequest(), [])', "离开客户开发页面时必须取消在途线索详情请求");
assertIncludes(app, 'if (refreshed) onMessage(lead.id, success);', "线索操作刷新必须仅在原线索仍处于活动状态时显示成功消息");
assertIncludes(app, 'onMessage={(leadId, value) => { if (leadDetailRequestRef.current.selectedLeadId === leadId) setDetailMessage(value); }}', "线索操作消息必须按当前抽屉线索隔离");
assertIncludes(app, 'crmLeadAnalytics()', "开发分析必须读取专用后端 analytics 接口");
assertIncludes(app, 'crmLeadDuplicateCheck(', "线索详情必须展示后端重复线索预警");
assertIncludes(app, 'input("address", "详细地址")', "客户开发新建和编辑表单必须提供详细地址字段");
assertIncludes(app, 'input("customer_group_name", "客户群名称")', "客户开发新建和编辑表单必须提供客户群名称字段");
assertIncludes(app, 'address: form.address.trim() || null', "详细地址必须提交到客户开发接口");
assertIncludes(app, 'customer_group_name: form.customer_group_name.trim() || null', "客户群名称必须提交到客户开发接口");
assertIncludes(app, 'precheckCrmLeadDuplicates(', "线索创建和资料更新必须在提交前执行重复预检");
assertCountAtLeast(app, 'await precheckCrmLeadDuplicates(', 2, "创建与更新流程都必须等待重复预检结果");
assertIncludes(app, 'duplicateCheck.has_blocking_duplicates', "重复预检必须阻止明确重复项提交");
assertIncludes(app, 'duplicateCheck.requires_acknowledgement', "同名或相似线索必须经过人工确认");
assertIncludes(app, 'duplicateCheck.has_hidden_duplicates', "预检必须提示无权查看的重复候选");
assertIncludes(app, 'duplicateAcknowledged', "相似线索建议必须经人工确认后再提交");
assertIncludes(app, 'duplicate_acknowledged: duplicateAcknowledged', "人工确认结果必须提交给后端复核");
assertIncludes(app, 'createCrmLeadFollowup(', "线索详情必须支持记录跟进");
assertIncludes(app, 'assignCrmLead(', "线索详情必须支持分配负责人");
assertIncludes(app, 'updateCrmLead(', "线索详情必须支持维护产品意向和推进状态");
assertIncludes(app, 'draft: ["draft", "active", "qualified", "closed", "rejected"]', "待接触线索必须允许直接确认意向");
assertIncludes(app, 'closed: ["closed", "active"]', "已关闭线索必须提供重新推进入口");
assertIncludes(app, 'rejected: ["rejected", "active"]', "暂不合作线索必须提供重新激活入口");
assertIncludes(app, 'conversion_pending: ["conversion_pending"]', "转正审批中的线索不得手工切换阶段");
assertIncludes(app, 'converted: ["converted"]', "已转正线索不得手工回退阶段");
assertIncludes(app, 'crmLeadEditableStatusTransitions[lead.status]', "阶段下拉必须与后端允许的状态流转保持一致");
assertIncludes(app, 'createCrmLeadConversionApprovalDraft(', "线索详情必须发起转正审批");
assertIncludes(app, 'leadConversionApprovalState(', "转正操作必须区分活动审批与终态审批");
assertIncludes(app, '["draft", "submitted", "under_review", "need_supplement"]', "草稿、审批中和待补充必须视为活动审批");
assertIncludes(app, '["rejected", "cancelled"]', "已驳回和已撤回必须视为可重新发起的终态审批");
assertIncludes(app, '(!lead.current_approval_id || approvalState.terminalResubmittable)', "存在活动审批时不能重复发起转正");
assertIncludes(app, 'approval(lead.current_approval_id)', "线索抽屉必须读取当前转正审批状态");
assertIncludes(app, 'terminalResubmittable', "已驳回或已撤回的转正审批必须允许重新发起");
assertIncludes(app, 'window.addEventListener("popstate", onLeadPopState)', "线索池与开发分析页签必须响应浏览器前进后退");
assertIncludes(app, 'crmLeadAssigneeOptions()', "负责人选择必须使用客户开发专用候选接口");
assertNotIncludes(app, 'void users().then((rows) => setUsersForAssignment', "客户开发不能调用需要 user.view 的用户列表接口");
assertIncludes(app, 'break-all', "联系电话等长文本必须允许断行");
assertIncludes(app, 'truncate', "线索卡片长文本必须限制宽度");
assertIncludes(app, '转正后会新建客户主档', "转正操作必须说明业务结果");
assertIncludes(app, 'approval_type === "crm_lead_convert"', "线索转正审批必须使用专门的业务详情视图");
assertIncludes(app, '<CrmLeadConversionApprovalSummary', "线索转正审批首屏必须展示业务摘要");
assertIncludes(app, '线索转正结果', "线索转正审批必须以业务结果说明为首屏标题");
assertIncludes(app, '申请前', "线索转正审批必须展示转正前状态");
assertIncludes(app, '转正后', "线索转正审批必须展示转正后状态");
assertIncludes(app, '项目预填', "线索转正审批必须展示项目预填状态");
assertIncludes(app, '!isLeadConversion && !isFollowupApproval && currentApproval.approval_type !== "crm_project_create" ? <ApprovalContextSummary', "专属业务审批不应在首屏回退到通用技术上下文");
assertIncludes(app, '<details className="rounded-lg border border-slate-200 bg-white p-4">', "系统信息必须默认折叠，避免原始载荷占据审批首屏");
assertIncludes(app, '重复线索需先核实', "页面必须说明重复线索风险");
assertIncludes(app, '客户开发权限说明', "页面必须提供权限说明");
assertNotIncludes(app, '线索 ID：{lead.id}', "线索技术 ID 不应默认展示");

assertIncludes(client, 'export type CrmLeadRow', "客户端需要定义线索行合同");
assertIncludes(client, 'export type CrmLeadAnalytics', "客户端需要定义线索分析合同");
assertIncludes(client, 'export function crmLeadsPage', "客户端需要提供线索分页请求");
assertIncludes(client, 'export function crmLeadDetail', "客户端需要提供线索详情请求");
assertIncludes(client, 'export function crmLeadDetail(leadId: number, options: RequestInit = {})', "线索详情请求必须支持取消信号");
assertIncludes(client, 'export function crmLeadAnalytics', "客户端需要提供线索专用分析请求");
assertIncludes(client, 'export function crmLeadDuplicateCheck', "客户端需要提供重复检查请求");
assertIncludes(client, 'export function assignCrmLead', "客户端需要提供分配请求");
assertIncludes(client, 'export type CrmLeadAssigneeOption', "客户端需要定义安全的负责人候选合同");
assertIncludes(client, 'export function crmLeadAssigneeOptions', "客户端需要提供客户开发负责人候选请求");
assertIncludes(client, '"/api/v1/crm/leads/assignee-options"', "负责人候选必须使用客户开发专用接口");
assertIncludes(client, 'export function createCrmLeadFollowup', "客户端需要提供跟进请求");
assertIncludes(client, 'export function createCrmLeadConversionApprovalDraft', "客户端需要提供转正审批请求");

console.log("CRM 客户开发工作台断言通过");
