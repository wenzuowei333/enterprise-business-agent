package com.demo.management.data

import retrofit2.http.GET
import okhttp3.RequestBody

interface MobileApi {
    @GET("mobile/bootstrap")
    suspend fun bootstrap(): BootstrapPayload

    @GET("mobile/home")
    suspend fun home(): HomePayload

    @GET("mobile/v2/workbench")
    suspend fun workbench(): WorkbenchPayload

    @GET("mobile/v2/execution")
    suspend fun execution(): ExecutionPayload

    @GET("mobile/v2/exceptions")
    suspend fun exceptions(
        @retrofit2.http.Query("domain") domain: String? = null,
        @retrofit2.http.Query("severity") severity: String? = null,
        @retrofit2.http.Query("case_status") status: String? = null,
        @retrofit2.http.Query("assignment") assignment: String? = null,
        @retrofit2.http.Query("q") q: String? = null,
        @retrofit2.http.Query("limit") limit: Int = 20,
        @retrofit2.http.Query("offset") offset: Int = 0,
    ): MobileExceptionPage

    @GET("mobile/v2/exceptions/{caseNo}")
    suspend fun exceptionDetail(@retrofit2.http.Path("caseNo") caseNo: String): MobileExceptionDetail

    @retrofit2.http.POST("mobile/v2/exceptions/{caseNo}/diagnoses")
    suspend fun requestExceptionDiagnosis(
        @retrofit2.http.Path("caseNo") caseNo: String,
        @retrofit2.http.Body body: MobileDiagnosisRequest = MobileDiagnosisRequest(),
    ): MobileDiagnosisJob

    @GET("mobile/v2/diagnosis-jobs/{jobId}")
    suspend fun diagnosisJob(@retrofit2.http.Path("jobId") jobId: Long): MobileDiagnosisJob

    @GET("mobile/v2/ai/actions")
    suspend fun aiActions(
        @retrofit2.http.Query("domain") domain: String? = null,
        @retrofit2.http.Query("review_status") reviewStatus: String? = "pending",
        @retrofit2.http.Query("limit") limit: Int = 20,
        @retrofit2.http.Query("offset") offset: Int = 0,
    ): MobileAiActionPage

    @retrofit2.http.POST("mobile/v2/ai/actions/{proposalNo}/validate")
    suspend fun validateAiAction(@retrofit2.http.Path("proposalNo") proposalNo: String): MobileAiActionValidation

    @retrofit2.http.POST("mobile/v2/ai/actions/{proposalNo}/execute")
    suspend fun executeAiAction(
        @retrofit2.http.Path("proposalNo") proposalNo: String,
        @retrofit2.http.Body body: MobileAiActionExecuteRequest,
    ): MobileAiActionExecution

    @GET("mobile/v2/customers/{customerCode}/tags")
    suspend fun customerTags(@retrofit2.http.Path("customerCode") customerCode: String): MobileCustomerTagPayload

    @GET("mobile/v2/deliveries")
    suspend fun deliveries(
        @retrofit2.http.Query("q") query: String? = null,
        @retrofit2.http.Query("status") status: String? = null,
        @retrofit2.http.Query("limit") limit: Int = 20,
        @retrofit2.http.Query("offset") offset: Int = 0,
    ): MobileDeliveryPage

    @retrofit2.http.POST("mobile/v2/deliveries/{deliveryId}/events")
    suspend fun addDeliveryEvent(
        @retrofit2.http.Path("deliveryId") deliveryId: Long,
        @retrofit2.http.Body body: MobileDeliveryEventRequest,
    ): MobileDeliveryTask

    @GET("mobile/users/options")
    suspend fun userOptions(
        @retrofit2.http.Query("q") q: String? = null,
        @retrofit2.http.Query("limit") limit: Int = 50,
        @retrofit2.http.Query("offset") offset: Int = 0,
    ): PageResult<MobileUserOption>

    @GET("mobile/customers/options")
    suspend fun customerOptions(
        @retrofit2.http.Query("q") q: String? = null,
        @retrofit2.http.Query("limit") limit: Int = 20,
        @retrofit2.http.Query("offset") offset: Int = 0,
    ): PageResult<MobileCustomerOption>

    @retrofit2.http.POST("mobile/projects/approval-draft")
    suspend fun createProjectDraft(@retrofit2.http.Body payload: CrmProjectDraftRequest): ApprovalSummary

    @retrofit2.http.PATCH("mobile/projects/approval-draft/{approvalId}")
    suspend fun updateProjectDraft(
        @retrofit2.http.Path("approvalId") approvalId: Long,
        @retrofit2.http.Body payload: CrmProjectDraftRequest,
    ): ApprovalDetailEnvelope

    @retrofit2.http.POST("mobile/projects/approval-draft/{approvalId}/submit")
    suspend fun submitProjectDraft(
        @retrofit2.http.Path("approvalId") approvalId: Long,
        @retrofit2.http.Body payload: ApprovalActionPayload = ApprovalActionPayload(),
    ): ApprovalDetailEnvelope

    @GET("mobile/customers/linked")
    suspend fun linkedCustomers(
        @retrofit2.http.Query("q") q: String? = null,
        @retrofit2.http.Query("scope") scope: String? = null,
        @retrofit2.http.Query("limit") limit: Int = 20,
        @retrofit2.http.Query("offset") offset: Int = 0,
    ): LinkedCustomerPage

    @GET("mobile/customers/{customerCode}/context")
    suspend fun customerContext(@retrofit2.http.Path("customerCode") customerCode: String): CustomerContext

    @GET("mobile/v2/customers/{customerCode}/panorama")
    suspend fun customerPanorama(@retrofit2.http.Path("customerCode") customerCode: String): CustomerPanorama

    @GET("mobile/tasks")
    suspend fun tasks(
        @retrofit2.http.Query("q") q: String? = null,
        @retrofit2.http.Query("status_value") status: String? = null,
        @retrofit2.http.Query("overdue") overdue: Boolean? = null,
        @retrofit2.http.Query("is_blocked") blocked: Boolean? = null,
        @retrofit2.http.Query("need_support") needSupport: Boolean? = null,
        @retrofit2.http.Query("is_closed") closed: Boolean? = null,
        @retrofit2.http.Query("limit") limit: Int = 20,
        @retrofit2.http.Query("offset") offset: Int = 0,
    ): CrmTaskPage

    @GET("mobile/tasks/{taskId}")
    suspend fun taskDetail(@retrofit2.http.Path("taskId") taskId: Long): CrmTaskDetail

    @retrofit2.http.POST("mobile/followups")
    suspend fun createFollowup(@retrofit2.http.Body payload: FollowupApprovalRequest): ApprovalSummary

    @retrofit2.http.POST("mobile/customers/{customerCode}/profile")
    suspend fun updateCustomerProfile(
        @retrofit2.http.Path("customerCode") customerCode: String,
        @retrofit2.http.Body payload: RequestBody,
    ): CustomerProfileUpdateResult

    @retrofit2.http.POST("mobile/customers/{customerCode}/business-profile")
    suspend fun updateBusinessProfile(
        @retrofit2.http.Path("customerCode") customerCode: String,
        @retrofit2.http.Body payload: BusinessProfileUpdateRequest,
    ): BusinessProfileUpdateResult

    @GET("mobile/work-items")
    suspend fun workItems(
        @retrofit2.http.Query("q") q: String? = null,
        @retrofit2.http.Query("open_only") openOnly: Boolean = true,
        @retrofit2.http.Query("limit") limit: Int = 20,
        @retrofit2.http.Query("offset") offset: Int = 0,
    ): WorkItemPage

    @retrofit2.http.POST("mobile/work-items/{itemId}/actions")
    suspend fun workItemAction(
        @retrofit2.http.Path("itemId") itemId: Long,
        @retrofit2.http.Query("action") action: String,
        @retrofit2.http.Body payload: WorkItemActionPayload,
    ): WorkItemRow

    @GET("mobile/approvals")
    suspend fun approvals(
        @retrofit2.http.Query("q") q: String? = null,
        @retrofit2.http.Query("scope") scope: String = "pending",
        @retrofit2.http.Query("mode") mode: String = "to_handle",
        @retrofit2.http.Query("limit") limit: Int = 20,
        @retrofit2.http.Query("offset") offset: Int = 0,
    ): ApprovalPage

    @GET("mobile/approvals/{approvalId}")
    suspend fun approvalDetail(@retrofit2.http.Path("approvalId") approvalId: Long): ApprovalDetailEnvelope

    @retrofit2.http.POST("mobile/approvals/{approvalId}/actions")
    suspend fun approvalAction(
        @retrofit2.http.Path("approvalId") approvalId: Long,
        @retrofit2.http.Query("action") action: String,
        @retrofit2.http.Body payload: ApprovalActionPayload,
    ): ApprovalDetailEnvelope

    @retrofit2.http.Multipart
    @retrofit2.http.POST("mobile/approvals/{approvalId}/attachments")
    suspend fun uploadApprovalAttachment(
        @retrofit2.http.Path("approvalId") approvalId: Long,
        @retrofit2.http.Part file: okhttp3.MultipartBody.Part,
    ): okhttp3.ResponseBody
}

data class ApprovalActionPayload(val comment: String? = null)

data class ApprovalDetailEnvelope(
    val approval: ApprovalSummary,
    val events: List<ApprovalEvent> = emptyList(),
)
