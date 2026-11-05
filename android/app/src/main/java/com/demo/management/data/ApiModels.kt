package com.demo.management.data

import com.squareup.moshi.Json
import com.demo.management.data.round6.LeadRow

data class MobileLoginRequest(
    val username: String,
    val password: String,
    @Json(name = "device_id") val deviceId: String,
    @Json(name = "device_name") val deviceName: String,
    @Json(name = "app_version") val appVersion: String? = null,
    @Json(name = "android_version") val androidVersion: String? = null,
    @Json(name = "device_model") val deviceModel: String? = null,
)

data class MobileRefreshRequest(
    @Json(name = "refresh_token") val refreshToken: String,
    @Json(name = "device_id") val deviceId: String,
)

data class MobileTokenResponse(
    @Json(name = "access_token") val accessToken: String,
    @Json(name = "refresh_token") val refreshToken: String,
    @Json(name = "expires_in") val expiresIn: Int,
    val user: MobileUser,
)

data class MobileUser(
    val id: Long,
    val username: String,
    @Json(name = "real_name") val realName: String,
    @Json(name = "employee_code") val employeeCode: String? = null,
    val role: String,
    val status: String,
    @Json(name = "avatar_url") val avatarUrl: String? = null,
)

data class MobileNavigationItem(
    val key: String,
    val label: String,
)

data class MobileAppConfig(
    val name: String,
    val channel: String,
    @Json(name = "page_size") val pageSize: Int = 20,
    @Json(name = "latest_version") val latestVersion: String,
    @Json(name = "latest_version_code") val latestVersionCode: Int = 1,
    @Json(name = "minimum_supported_version") val minimumSupportedVersion: String,
    @Json(name = "minimum_supported_version_code") val minimumSupportedVersionCode: Int = 1,
    @Json(name = "download_url") val downloadUrl: String?,
    @Json(name = "apk_sha256") val apkSha256: String? = null,
    @Json(name = "update_mode") val updateMode: String = "optional",
    @Json(name = "release_notes") val releaseNotes: String? = null,
    @Json(name = "onboarding_version") val onboardingVersion: Int = 0,
    @Json(name = "help_enabled") val helpEnabled: Boolean = true,
    @Json(name = "feedback_enabled") val feedbackEnabled: Boolean = true,
    @Json(name = "mobile_feature_liquid_ui") val liquidUiEnabled: Boolean = true,
    @Json(name = "mobile_feature_liquid_full_effect") val liquidFullEffectEnabled: Boolean = true,
    @Json(name = "mobile_feature_dark_theme") val darkThemeEnabled: Boolean = true,
    @Json(name = "force_reduced_glass") val forceReducedGlass: Boolean = false,
    @Json(name = "ui_theme_version") val uiThemeVersion: String = "liquid_v1",
    @Json(name = "feature_flags") val featureFlags: Map<String, Boolean> = emptyMap(),
)

data class BootstrapPayload(
    val user: MobileUser,
    val permissions: List<String> = emptyList(),
    val navigation: List<MobileNavigationItem> = emptyList(),
    @Json(name = "scope_revision") val scopeRevision: String? = null,
    val app: MobileAppConfig,
)

data class HomePayload(
    @Json(name = "generated_at") val generatedAt: String?,
    val summary: HomeSummary = HomeSummary(),
    val actions: List<HomeAction> = emptyList(),
)

data class HomeSummary(
    @Json(name = "task_open") val taskOpen: Int = 0,
    @Json(name = "task_overdue") val taskOverdue: Int = 0,
    @Json(name = "approval_pending") val approvalPending: Int = 0,
    @Json(name = "work_item_open") val workItemOpen: Int = 0,
    @Json(name = "draft_count") val draftCount: Int = 0,
    @Json(name = "supplement_count") val supplementCount: Int = 0,
)

data class HomeAction(
    val key: String,
    val title: String,
    val detail: String,
    val tone: String,
    val count: Int,
)

data class WorkbenchPayload(
    @Json(name = "generated_at") val generatedAt: String? = null,
    @Json(name = "date_label") val dateLabel: String = "",
    val headline: String = "",
    val summary: WorkbenchSummary = WorkbenchSummary(),
    @Json(name = "today_queue") val todayQueue: WorkbenchQueue = WorkbenchQueue(),
    val projects: WorkbenchProjectPage = WorkbenchProjectPage(),
    val approvals: WorkbenchApprovalPage = WorkbenchApprovalPage(),
    val shortcuts: WorkbenchShortcuts = WorkbenchShortcuts(),
)

data class WorkbenchSummary(
    @Json(name = "active_projects") val activeProjects: Int = 0,
    @Json(name = "open_tasks") val openTasks: Int = 0,
    @Json(name = "pending_approvals") val pendingApprovals: Int = 0,
    @Json(name = "overdue_tasks") val overdueTasks: Int = 0,
    @Json(name = "open_support") val openSupport: Int = 0,
)

data class WorkbenchQueue(
    val items: List<WorkbenchQueueItem> = emptyList(),
    val total: Int = 0,
)

data class WorkbenchQueueItem(
    val key: String,
    val kind: String,
    val title: String,
    val subtitle: String? = null,
    @Json(name = "status_label") val statusLabel: String,
    val tone: String = "neutral",
    @Json(name = "due_at") val dueAt: String? = null,
    val target: WorkbenchTarget = WorkbenchTarget(),
)

data class WorkbenchTarget(
    val page: String = "home",
    @Json(name = "task_id") val taskId: Long? = null,
    @Json(name = "project_id") val projectId: Long? = null,
    @Json(name = "approval_id") val approvalId: Long? = null,
    @Json(name = "work_item_id") val workItemId: Long? = null,
)

data class WorkbenchProjectPage(
    val items: List<WorkbenchProject> = emptyList(),
    val total: Int = 0,
)

data class WorkbenchProject(
    val id: Long,
    @Json(name = "project_code") val projectCode: String,
    @Json(name = "project_name") val projectName: String,
    val status: String,
    @Json(name = "due_date") val dueDate: String? = null,
    val overdue: Boolean = false,
    @Json(name = "open_tasks") val openTasks: Int = 0,
    @Json(name = "total_tasks") val totalTasks: Int = 0,
)

data class WorkbenchApprovalPage(
    val items: List<WorkbenchApproval> = emptyList(),
    val total: Int = 0,
)

data class WorkbenchApproval(
    val id: Long,
    @Json(name = "approval_no") val approvalNo: String,
    val title: String,
    val status: String,
    val priority: String,
    @Json(name = "submitted_at") val submittedAt: String? = null,
)

data class WorkbenchShortcuts(
    @Json(name = "create_project") val createProject: Boolean = false,
    @Json(name = "view_approvals") val viewApprovals: Boolean = false,
    @Json(name = "view_support") val viewSupport: Boolean = false,
)

data class ExecutionPayload(
    @Json(name = "generated_at") val generatedAt: String? = null,
    val summary: ExecutionSummary = ExecutionSummary(),
    val projects: ExecutionProjectPage = ExecutionProjectPage(),
    @Json(name = "my_tasks") val myTasks: ExecutionTaskPage = ExecutionTaskPage(),
    val capabilities: ExecutionCapabilities = ExecutionCapabilities(),
)

data class ExecutionSummary(
    @Json(name = "project_total") val projectTotal: Int = 0,
    @Json(name = "active_projects") val activeProjects: Int = 0,
    @Json(name = "overdue_projects") val overdueProjects: Int = 0,
    @Json(name = "my_open_tasks") val myOpenTasks: Int = 0,
    @Json(name = "overdue_tasks") val overdueTasks: Int = 0,
    @Json(name = "support_tasks") val supportTasks: Int = 0,
    @Json(name = "blocked_tasks") val blockedTasks: Int = 0,
    @Json(name = "pending_approvals") val pendingApprovals: Int = 0,
    @Json(name = "supplement_requests") val supplementRequests: Int = 0,
)

data class ExecutionProjectPage(
    val items: List<ExecutionProject> = emptyList(),
    val total: Int = 0,
)

data class ExecutionProject(
    val id: Long,
    @Json(name = "project_code") val projectCode: String,
    @Json(name = "project_name") val projectName: String,
    @Json(name = "project_type") val projectType: String? = null,
    val purpose: String? = null,
    val status: String,
    @Json(name = "approval_status") val approvalStatus: String = "draft",
    @Json(name = "start_date") val startDate: String? = null,
    @Json(name = "due_date") val dueDate: String? = null,
    val overdue: Boolean = false,
    @Json(name = "task_total") val taskTotal: Int = 0,
    @Json(name = "task_open") val taskOpen: Int = 0,
    @Json(name = "task_need_support") val taskNeedSupport: Int = 0,
    @Json(name = "task_blocked") val taskBlocked: Int = 0,
    @Json(name = "next_step_action") val nextStepAction: String? = null,
)

data class ExecutionTaskPage(
    val items: List<CrmTaskRow> = emptyList(),
    val total: Int = 0,
)

data class ExecutionCapabilities(
    @Json(name = "create_project") val createProject: Boolean = false,
    @Json(name = "submit_followup") val submitFollowup: Boolean = false,
    @Json(name = "view_approvals") val viewApprovals: Boolean = false,
)

data class MobileExceptionPage(
    @Json(name = "generated_at") val generatedAt: String? = null,
    val summary: MobileExceptionSummary = MobileExceptionSummary(),
    val items: List<MobileExceptionCase> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
    val capabilities: MobileExceptionCapabilities = MobileExceptionCapabilities(),
)

data class MobileExceptionSummary(
    val total: Int = 0,
    val open: Int = 0,
    @Json(name = "action_required") val actionRequired: Int = 0,
    val processing: Int = 0,
    val blocked: Int = 0,
    val resolved: Int = 0,
    val ignored: Int = 0,
    val overdue: Int = 0,
    @Json(name = "due_soon") val dueSoon: Int = 0,
    @Json(name = "by_domain") val byDomain: Map<String, Int> = emptyMap(),
    @Json(name = "by_severity") val bySeverity: Map<String, Int> = emptyMap(),
)

data class MobileExceptionCapabilities(
    val diagnose: Boolean = false,
    @Json(name = "execute_action") val executeAction: Boolean = false,
)

data class MobileExceptionCase(
    val id: Long,
    @Json(name = "case_no") val caseNo: String,
    val domain: String,
    @Json(name = "diagnosis_supported") val diagnosisSupported: Boolean = false,
    @Json(name = "rule_code") val ruleCode: String,
    val title: String,
    val severity: String,
    val status: String,
    @Json(name = "occurrence_type") val occurrenceType: String = "new",
    @Json(name = "resource_type") val resourceType: String? = null,
    @Json(name = "resource_id") val resourceId: String? = null,
    @Json(name = "resource_code") val resourceCode: String? = null,
    @Json(name = "resource_name") val resourceName: String? = null,
    @Json(name = "source_type") val sourceType: String,
    @Json(name = "source_batch_kind") val sourceBatchKind: String? = null,
    @Json(name = "source_batch_id") val sourceBatchId: Long? = null,
    @Json(name = "data_date") val dataDate: String? = null,
    @Json(name = "evidence_version") val evidenceVersion: String,
    val reason: String,
    @Json(name = "initial_guidance") val initialGuidance: String? = null,
    @Json(name = "affected_rows") val affectedRows: Int = 0,
    @Json(name = "assignee_name") val assigneeName: String? = null,
    @Json(name = "due_at") val dueAt: String? = null,
    @Json(name = "last_seen_at") val lastSeenAt: String,
    @Json(name = "sla_status") val slaStatus: String? = null,
    @Json(name = "is_mine") val isMine: Boolean = false,
    @Json(name = "processing_kind") val processingKind: String? = null,
)

data class MobileExceptionDetail(
    val id: Long,
    @Json(name = "case_no") val caseNo: String,
    val domain: String,
    @Json(name = "diagnosis_supported") val diagnosisSupported: Boolean = false,
    @Json(name = "rule_code") val ruleCode: String,
    val title: String,
    val severity: String,
    val status: String,
    @Json(name = "occurrence_type") val occurrenceType: String = "new",
    @Json(name = "resource_code") val resourceCode: String? = null,
    @Json(name = "resource_name") val resourceName: String? = null,
    @Json(name = "evidence_version") val evidenceVersion: String,
    val reason: String,
    @Json(name = "initial_guidance") val initialGuidance: String? = null,
    @Json(name = "affected_rows") val affectedRows: Int = 0,
    @Json(name = "assignee_name") val assigneeName: String? = null,
    @Json(name = "due_at") val dueAt: String? = null,
    @Json(name = "last_seen_at") val lastSeenAt: String,
    @Json(name = "sla_status") val slaStatus: String? = null,
    val evidence: Map<String, Any?>? = null,
    val diagnoses: List<Map<String, Any?>> = emptyList(),
    val events: List<Map<String, Any?>> = emptyList(),
    val actions: List<Map<String, Any?>> = emptyList(),
    @Json(name = "active_diagnosis_job") val activeDiagnosisJob: Map<String, Any?>? = null,
    val capabilities: MobileExceptionCapabilities = MobileExceptionCapabilities(),
)

data class MobileDiagnosisRequest(val force: Boolean = false)

data class MobileDiagnosisJob(
    val id: Long,
    @Json(name = "job_no") val jobNo: String,
    @Json(name = "case_no") val caseNo: String,
    @Json(name = "evidence_version") val evidenceVersion: String,
    @Json(name = "trigger_type") val triggerType: String,
    val status: String,
    val reused: Boolean = false,
    val attempts: Int = 0,
    @Json(name = "max_attempts") val maxAttempts: Int = 0,
    @Json(name = "error_message") val errorMessage: String? = null,
    @Json(name = "created_at") val createdAt: String,
    @Json(name = "updated_at") val updatedAt: String? = null,
    @Json(name = "completed_at") val completedAt: String? = null,
)

data class MobileAiActionPage(
    val items: List<MobileAiActionProposal> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
)

data class MobileAiActionProposal(
    val id: Long,
    @Json(name = "proposal_no") val proposalNo: String,
    val domain: String,
    @Json(name = "action_type") val actionType: String,
    @Json(name = "resource_type") val resourceType: String? = null,
    @Json(name = "resource_id") val resourceId: String? = null,
    val status: String,
    @Json(name = "review_status") val reviewStatus: String,
    @Json(name = "risk_level") val riskLevel: String? = null,
    @Json(name = "requires_confirmation") val requiresConfirmation: Boolean = true,
    val parameters: Map<String, Any?> = emptyMap(),
    val impact: Map<String, Any?> = emptyMap(),
    @Json(name = "source_refs") val sourceRefs: List<String> = emptyList(),
    val executable: Boolean = false,
    val blockers: List<String> = emptyList(),
    @Json(name = "created_at") val createdAt: String,
    @Json(name = "updated_at") val updatedAt: String,
)

data class MobileAiActionValidation(
    val proposal: MobileAiActionProposal,
    @Json(name = "validation_token") val validationToken: String? = null,
    @Json(name = "validation_expires_at") val validationExpiresAt: String? = null,
)

data class MobileAiActionExecuteRequest(
    @Json(name = "expected_updated_at") val expectedUpdatedAt: String,
    val confirmation: Boolean = true,
    @Json(name = "idempotency_key") val idempotencyKey: String,
    @Json(name = "validation_token") val validationToken: String,
)

data class MobileAiActionExecution(
    @Json(name = "execution_no") val executionNo: String,
    @Json(name = "proposal_no") val proposalNo: String,
    val status: String,
    val attempts: Int = 0,
    val result: Map<String, Any?> = emptyMap(),
    val verification: Map<String, Any?> = emptyMap(),
    @Json(name = "error_code") val errorCode: String? = null,
    @Json(name = "completed_at") val completedAt: String? = null,
)

data class MobileCustomerTagPayload(
    @Json(name = "generated_at") val generatedAt: String? = null,
    val customer: LinkedCustomerRow,
    val tags: CustomerPanoramaTags = CustomerPanoramaTags(),
    val capabilities: MobileCustomerTagCapabilities = MobileCustomerTagCapabilities(),
)

data class MobileCustomerTagCapabilities(
    @Json(name = "view_history") val viewHistory: Boolean = false,
    @Json(name = "submit_change") val submitChange: Boolean = false,
)

data class MobileDeliveryPage(
    val items: List<MobileDeliveryTask> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
    val capabilities: MobileDeliveryCapabilities = MobileDeliveryCapabilities(),
)

data class MobileDeliveryCapabilities(val manage: Boolean = false)

data class MobileDeliveryTask(
    val id: Long,
    @Json(name = "delivery_no") val deliveryNo: String,
    @Json(name = "order_id") val orderId: Long,
    @Json(name = "order_no") val orderNo: String? = null,
    @Json(name = "customer_code") val customerCode: String? = null,
    @Json(name = "customer_name") val customerName: String? = null,
    val status: String,
    @Json(name = "planned_at") val plannedAt: String? = null,
    @Json(name = "delivery_address") val deliveryAddress: String? = null,
    @Json(name = "requirements_json") val requirements: List<Map<String, Any?>> = emptyList(),
    @Json(name = "assignee_user_id") val assigneeUserId: Long? = null,
    @Json(name = "signed_by") val signedBy: String? = null,
    @Json(name = "signed_at") val signedAt: String? = null,
    @Json(name = "exception_note") val exceptionNote: String? = null,
    @Json(name = "created_at") val createdAt: String,
    @Json(name = "updated_at") val updatedAt: String,
    val events: List<MobileDeliveryEvent> = emptyList(),
)

data class MobileDeliveryEvent(
    val id: Long,
    @Json(name = "delivery_id") val deliveryId: Long,
    @Json(name = "event_type") val eventType: String,
    @Json(name = "from_status") val fromStatus: String? = null,
    @Json(name = "to_status") val toStatus: String? = null,
    val note: String? = null,
    @Json(name = "created_at") val createdAt: String,
)

data class MobileDeliveryEventRequest(
    @Json(name = "expected_updated_at") val expectedUpdatedAt: String,
    @Json(name = "idempotency_key") val idempotencyKey: String,
    @Json(name = "event_type") val eventType: String,
    @Json(name = "to_status") val toStatus: String,
    val note: String? = null,
    @Json(name = "signed_by") val signedBy: String? = null,
)

data class PageResult<T>(
    val items: List<T> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
)

data class MobileUserOption(
    val id: Long,
    val username: String,
    @Json(name = "real_name") val realName: String,
    @Json(name = "employee_code") val employeeCode: String? = null,
    val role: String,
    val label: String,
)

data class MobileCustomerOption(
    @Json(name = "customer_code") val customerCode: String,
    @Json(name = "customer_name") val customerName: String,
    @Json(name = "customer_short_name") val customerShortName: String? = null,
    @Json(name = "salesperson_employee_code") val salespersonEmployeeCode: String? = null,
    @Json(name = "salesperson_name") val salespersonName: String? = null,
    @Json(name = "contact_name") val contactName: String? = null,
    @Json(name = "contact_phone") val contactPhone: String? = null,
    val region: String? = null,
    @Json(name = "customer_type") val customerType: String? = null,
)

data class CrmProjectDraftRequest(
    val title: String? = null,
    val description: String? = null,
    val priority: String = "normal",
    val submit: Boolean = false,
    val project: CrmProjectDraft,
    val tasks: List<CrmProjectTaskDraft>,
)

data class CrmProjectDraft(
    @Json(name = "project_name") val projectName: String,
    @Json(name = "project_type") val projectType: String? = null,
    val purpose: String? = null,
    @Json(name = "customer_scope_note") val customerScopeNote: String? = null,
    @Json(name = "business_line") val businessLine: String? = null,
    @Json(name = "landing_approver_user_id") val landingApproverUserId: Long? = null,
    @Json(name = "owner_user_id") val ownerUserId: Long? = null,
    @Json(name = "participant_user_ids") val participantUserIds: List<Long> = emptyList(),
    @Json(name = "progress_cc_user_ids") val progressCcUserIds: List<Long> = emptyList(),
    @Json(name = "assignment_mode") val assignmentMode: String = "flow_roles",
    @Json(name = "allow_unassigned_tasks") val allowUnassignedTasks: Boolean = false,
    @Json(name = "start_date") val startDate: String? = null,
    @Json(name = "due_date") val dueDate: String? = null,
    @Json(name = "minimum_action") val minimumAction: String? = null,
    @Json(name = "closure_standard") val closureStandard: String? = null,
    val status: String = "submitted",
    @Json(name = "approval_status") val approvalStatus: String = "draft",
)

data class CrmProjectTaskDraft(
    @Json(name = "customer_code") val customerCode: String,
    @Json(name = "executor_user_id") val executorUserId: Long? = null,
    @Json(name = "executor_employee_code") val executorEmployeeCode: String? = null,
    @Json(name = "business_issue_point") val businessIssuePoint: String? = null,
    @Json(name = "round_target") val roundTarget: String? = null,
    @Json(name = "feedback_due_at") val feedbackDueAt: String? = null,
    val status: String = "not_started",
)

data class ApprovalSummary(
    val id: Long,
    @Json(name = "approval_no") val approvalNo: String,
    val title: String,
    val status: String,
    val priority: String,
    @Json(name = "approval_type") val approvalType: String? = null,
    val description: String? = null,
    @Json(name = "applicant_user_label") val applicantUserLabel: String? = null,
    @Json(name = "current_handler_user_id") val currentHandlerUserId: Long? = null,
    @Json(name = "current_handler_user_label") val currentHandlerUserLabel: String? = null,
    @Json(name = "submitted_at") val submittedAt: String? = null,
    @Json(name = "reviewed_at") val reviewedAt: String? = null,
    @Json(name = "business_summary") val businessSummary: Map<String, Any?>? = null,
)

data class ApprovalPage(
    val items: List<ApprovalSummary> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
)

data class ApprovalEvent(
    @Json(name = "event_type") val eventType: String,
    @Json(name = "from_status") val fromStatus: String? = null,
    @Json(name = "to_status") val toStatus: String? = null,
    val comment: String? = null,
    @Json(name = "created_at") val createdAt: String,
)

data class LinkedCustomerPage(
    val items: List<LinkedCustomerRow> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
    val summary: LinkedCustomerSummary = LinkedCustomerSummary(),
)

data class LinkedCustomerSummary(
    @Json(name = "total_customers") val totalCustomers: Int = 0,
    @Json(name = "profile_incomplete") val profileIncomplete: Int = 0,
    @Json(name = "pending_action_customers") val pendingActionCustomers: Int = 0,
    @Json(name = "risk_customers") val riskCustomers: Int = 0,
)

data class LinkedCustomerRow(
    @Json(name = "customer_code") val customerCode: String,
    @Json(name = "customer_name") val customerName: String,
    @Json(name = "customer_short_name") val customerShortName: String? = null,
    @Json(name = "customer_type") val customerType: String? = null,
    val region: String? = null,
    @Json(name = "contact_name") val contactName: String? = null,
    @Json(name = "contact_phone") val contactPhone: String? = null,
    @Json(name = "contact_channel") val contactChannel: String? = null,
    @Json(name = "customer_group_name") val customerGroupName: String? = null,
    @Json(name = "customer_tags") val customerTags: List<String> = emptyList(),
    val address: String? = null,
    @Json(name = "base_info_completeness") val baseInfoCompleteness: String? = null,
    @Json(name = "salesperson_name") val salespersonName: String? = null,
    @Json(name = "latest_owner_next_action") val latestOwnerNextAction: String? = null,
    @Json(name = "latest_blocker_reason") val latestBlockerReason: String? = null,
    @Json(name = "latest_task_status") val latestTaskStatus: String? = null,
    @Json(name = "task_open") val taskOpen: Int = 0,
    @Json(name = "task_need_support") val taskNeedSupport: Int = 0,
    @Json(name = "task_blocked") val taskBlocked: Int = 0,
    @Json(name = "risk_level") val riskLevel: String = "normal",
    @Json(name = "customer_updated_at") val customerUpdatedAt: String? = null,
    @Json(name = "profile_updated_at") val profileUpdatedAt: String? = null,
    @Json(name = "last_activity_at") val lastActivityAt: String? = null,
)

data class CustomerPanorama(
    @Json(name = "generated_at") val generatedAt: String? = null,
    val customer: LinkedCustomerRow,
    val stats: Map<String, Int> = emptyMap(),
    val tags: CustomerPanoramaTags = CustomerPanoramaTags(),
    val projects: List<CustomerPanoramaProject> = emptyList(),
    val tasks: List<CrmTaskRow> = emptyList(),
    val timeline: List<CustomerTimelineItem> = emptyList(),
    val capabilities: CustomerPanoramaCapabilities = CustomerPanoramaCapabilities(),
)

data class CustomerPanoramaTags(
    val items: List<CustomerPanoramaTag> = emptyList(),
    @Json(name = "compatibility_tags") val compatibilityTags: List<String> = emptyList(),
    @Json(name = "review_due_count") val reviewDueCount: Int = 0,
)

data class CustomerPanoramaTag(
    val id: Long? = null,
    val name: String? = null,
    val category: String? = null,
    val color: String? = null,
    @Json(name = "is_primary") val isPrimary: Boolean = false,
    @Json(name = "review_date") val reviewDate: String? = null,
    val status: String? = null,
)

data class CustomerPanoramaProject(
    val id: Long,
    @Json(name = "project_code") val projectCode: String,
    @Json(name = "project_name") val projectName: String,
    val status: String,
    @Json(name = "due_date") val dueDate: String? = null,
    @Json(name = "task_open") val taskOpen: Int = 0,
    @Json(name = "task_total") val taskTotal: Int = 0,
)

data class CustomerTimelineItem(
    val key: String,
    val kind: String,
    val title: String,
    val detail: String? = null,
    val status: String? = null,
    @Json(name = "occurred_at") val occurredAt: String? = null,
    val target: WorkbenchTarget = WorkbenchTarget(),
)

data class CustomerPanoramaCapabilities(
    @Json(name = "edit_profile") val editProfile: Boolean = false,
    @Json(name = "edit_business_profile") val editBusinessProfile: Boolean = false,
    @Json(name = "view_tag_history") val viewTagHistory: Boolean = false,
)

data class CrmTaskPage(
    val items: List<CrmTaskRow> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
)

data class CrmTaskRow(
    val id: Long,
    @Json(name = "project_id") val projectId: Long,
    @Json(name = "task_code") val taskCode: String,
    @Json(name = "customer_code") val customerCode: String,
    @Json(name = "customer_name_snapshot") val customerName: String,
    @Json(name = "executor_name_snapshot") val executorName: String? = null,
    @Json(name = "business_issue_point") val businessIssuePoint: String? = null,
    @Json(name = "round_target") val roundTarget: String? = null,
    @Json(name = "feedback_due_at") val feedbackDueAt: String? = null,
    val status: String,
    @Json(name = "need_support") val needSupport: Boolean = false,
    @Json(name = "is_blocked") val isBlocked: Boolean = false,
    @Json(name = "is_closed") val isClosed: Boolean = false,
    @Json(name = "latest_owner_next_action") val latestOwnerNextAction: String? = null,
    @Json(name = "customer_profile_approval_status") val customerProfileStatus: String? = null,
    @Json(name = "business_profile_approval_status") val businessProfileStatus: String? = null,
    @Json(name = "updated_at") val updatedAt: String? = null,
    @Json(name = "project_name") val projectName: String? = null,
    @Json(name = "project_code") val projectCode: String? = null,
    @Json(name = "project_status") val projectStatus: String? = null,
)

data class SyncPullPayload(
    @Json(name = "next_cursor") val nextCursor: String,
    @Json(name = "scope_revision") val scopeRevision: String,
    @Json(name = "server_time") val serverTime: String,
    @Json(name = "full_snapshot") val fullSnapshot: Boolean,
    val upserts: SyncUpserts = SyncUpserts(),
    val deletions: SyncDeletions = SyncDeletions(),
    @Json(name = "authoritative_keys") val authoritativeKeys: SyncAuthoritativeKeys = SyncAuthoritativeKeys(),
    val dictionary: Map<String, List<String>> = emptyMap(),
)

data class SyncUpserts(
    val customers: List<LinkedCustomerRow> = emptyList(),
    val tasks: List<CrmTaskRow> = emptyList(),
    val leads: List<LeadRow> = emptyList(),
)

data class SyncDeletions(
    val customers: List<String> = emptyList(),
    val tasks: List<String> = emptyList(),
    val leads: List<String> = emptyList(),
)

data class SyncAuthoritativeKeys(
    val customers: List<String> = emptyList(),
    val tasks: List<String> = emptyList(),
    val leads: List<String> = emptyList(),
)

data class SyncOperationRequest(
    @Json(name = "client_operation_id") val clientOperationId: String,
    @Json(name = "device_id") val deviceId: String,
    @Json(name = "action_type") val actionType: String,
    @Json(name = "resource_type") val resourceType: String? = null,
    @Json(name = "resource_id") val resourceId: String? = null,
    @Json(name = "base_updated_at") val baseUpdatedAt: String? = null,
    val payload: Map<String, Any?> = emptyMap(),
    val attachments: List<Map<String, Any?>> = emptyList(),
    @Json(name = "created_at") val createdAt: String? = null,
)

data class SyncOperationBatch(val operations: List<SyncOperationRequest>)

data class SyncOperationResult(
    @Json(name = "client_operation_id") val clientOperationId: String,
    val status: String,
    @Json(name = "resource_type") val resourceType: String? = null,
    @Json(name = "resource_id") val resourceId: String? = null,
    val result: Map<String, Any?>? = null,
    val error: Map<String, Any?>? = null,
)

data class SyncOperationBatchResult(
    val items: List<SyncOperationResult> = emptyList(),
    val total: Int = 0,
)

data class SyncStatusPayload(
    val counts: Map<String, Int> = emptyMap(),
    val latest: List<SyncOperationResult> = emptyList(),
    @Json(name = "generated_at") val generatedAt: String? = null,
)

data class MobileDevice(
    val id: Long,
    @Json(name = "device_id") val deviceId: String,
    @Json(name = "device_name") val deviceName: String? = null,
    @Json(name = "app_version") val appVersion: String? = null,
    @Json(name = "android_version") val androidVersion: String? = null,
    @Json(name = "device_model") val deviceModel: String? = null,
    @Json(name = "last_used_at") val lastUsedAt: String? = null,
    @Json(name = "last_sync_at") val lastSyncAt: String? = null,
    @Json(name = "expires_at") val expiresAt: String,
    @Json(name = "revoked_at") val revokedAt: String? = null,
    @Json(name = "is_current") val isCurrent: Boolean = false,
    @Json(name = "notification_preferences") val notificationPreferences: Map<String, Boolean> = emptyMap(),
)

data class MobileDevicePage(
    val items: List<MobileDevice> = emptyList(),
    val total: Int = 0,
)

data class NotificationPreferencesUpdate(
    val approval: Boolean = true,
    val task: Boolean = true,
    val risk: Boolean = true,
)

data class QueuedSubmission<T>(
    val value: T? = null,
    val queued: Boolean = false,
    val operationId: String? = null,
    val attachmentsPending: Boolean = false,
)

data class CrmProjectSummary(
    val id: Long,
    @Json(name = "project_code") val projectCode: String,
    @Json(name = "project_name") val projectName: String,
    val status: String,
    val purpose: String? = null,
    @Json(name = "landing_approver_user_label") val landingApproverLabel: String? = null,
    @Json(name = "owner_user_label") val ownerLabel: String? = null,
)

data class CrmTaskDetail(
    val task: CrmTaskRow,
    val project: CrmProjectSummary,
    val approvals: List<ApprovalSummary> = emptyList(),
)

data class CustomerContext(
    val customer: LinkedCustomerRow,
    val crm: CustomerCrmContext,
)

data class CustomerCrmContext(
    val tasks: List<CrmTaskRow> = emptyList(),
    val approvals: List<ApprovalSummary> = emptyList(),
    val stats: Map<String, Int> = emptyMap(),
)

data class FollowupApprovalRequest(
    val title: String? = null,
    val description: String? = null,
    val priority: String = "normal",
    val submit: Boolean = true,
    val followup: FollowupPayload,
)

data class FollowupPayload(
    @Json(name = "project_id") val projectId: Long,
    @Json(name = "task_id") val taskId: Long,
    @Json(name = "followup_date") val followupDate: String? = null,
    val method: String? = null,
    @Json(name = "frontline_action") val frontlineAction: String? = null,
    @Json(name = "customer_feedback") val customerFeedback: String? = null,
    @Json(name = "current_need") val currentNeed: String? = null,
    @Json(name = "need_type") val needType: String? = null,
    @Json(name = "blocker_reason") val blockerReason: String? = null,
    @Json(name = "blocker_note") val blockerNote: String? = null,
    @Json(name = "next_action_type") val nextActionType: String? = null,
    @Json(name = "next_action") val nextAction: String? = null,
    @Json(name = "next_followup_at") val nextFollowupAt: String? = null,
    @Json(name = "minimum_action_done") val minimumActionDone: Boolean = false,
    @Json(name = "business_profile_updated") val businessProfileUpdated: Boolean = false,
    @Json(name = "business_profile_approval_id") val businessProfileApprovalId: Long? = null,
    @Json(name = "customer_profile_updated") val customerProfileUpdated: Boolean = false,
    @Json(name = "need_support") val needSupport: Boolean = false,
    @Json(name = "is_closed") val isClosed: Boolean = false,
    @Json(name = "valid_feedback") val validFeedback: Boolean = true,
    @Json(name = "review_status") val reviewStatus: String = "pending",
)

data class CustomerProfileUpdateResult(
    @Json(name = "changed_fields") val changedFields: List<String> = emptyList(),
    @Json(name = "audit_log_id") val auditLogId: Long? = null,
    @Json(name = "task_id") val taskId: Long,
    @Json(name = "synced_to_master") val syncedToMaster: Boolean,
)

data class BusinessProfileUpdateResult(
    @Json(name = "changed_fields") val changedFields: List<String> = emptyList(),
    @Json(name = "audit_log_id") val auditLogId: Long? = null,
    @Json(name = "task_id") val taskId: Long,
    @Json(name = "project_id") val projectId: Long,
    @Json(name = "synced_to_master") val syncedToMaster: Boolean,
)

data class BusinessProfileUpdateRequest(
    @Json(name = "business_customer_type") val businessCustomerType: String? = null,
    @Json(name = "confirmed_at") val confirmedAt: String? = null,
    @Json(name = "update_source") val updateSource: String? = null,
    @Json(name = "update_type") val updateType: String? = null,
    @Json(name = "business_status_label") val businessStatusLabel: String? = null,
    @Json(name = "business_status_note") val businessStatusNote: String? = null,
    @Json(name = "latest_update_note") val latestUpdateNote: String? = null,
    val products: List<BusinessProductPayload> = emptyList(),
    @Json(name = "recommended_products") val recommendedProducts: List<RecommendedProductPayload> = emptyList(),
)

data class BusinessProductPayload(
    @Json(name = "product_category") val productCategory: String? = null,
    val spec: String? = null,
    @Json(name = "common_brand") val commonBrand: String? = null,
    @Json(name = "monthly_usage") val monthlyUsage: String? = null,
    @Json(name = "cooperation_status") val cooperationStatus: String? = null,
    @Json(name = "opportunity_note") val opportunityNote: String? = null,
)

data class RecommendedProductPayload(
    @Json(name = "product_name") val productName: String? = null,
    val spec: String? = null,
    @Json(name = "recommended_quote") val recommendedQuote: String? = null,
    @Json(name = "recommend_reason") val recommendReason: String? = null,
    @Json(name = "customer_feedback") val customerFeedback: String? = null,
    @Json(name = "next_action") val nextAction: String? = null,
)

data class WorkItemPage(
    val items: List<WorkItemRow> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
)

data class WorkItemRow(
    val id: Long,
    @Json(name = "item_no") val itemNo: String,
    val title: String,
    val detail: String? = null,
    val priority: String,
    val status: String,
    @Json(name = "customer_code") val customerCode: String? = null,
    @Json(name = "customer_name") val customerName: String? = null,
    @Json(name = "project_name") val projectName: String? = null,
    @Json(name = "support_type") val supportType: String? = null,
    @Json(name = "support_detail") val supportDetail: String? = null,
    @Json(name = "assignee_name") val assigneeName: String? = null,
    @Json(name = "needs_next_action") val needsNextAction: Boolean = false,
)

data class WorkItemActionPayload(@Json(name = "resolution_note") val resolutionNote: String? = null)
