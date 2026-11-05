package com.demo.management.data

import com.demo.management.core.sync.NetworkFailurePolicy
import com.demo.management.data.local.FormDraftDao
import com.demo.management.data.local.FormDraftEntity
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import javax.inject.Inject
import javax.inject.Singleton
import android.net.Uri

@Singleton
class CrmActionRepository @Inject constructor(
    private val api: MobileApi,
    private val drafts: FormDraftDao,
    private val sync: SyncRepository,
    moshi: Moshi,
) {
    private val followupAdapter = moshi.adapter(FollowupApprovalRequest::class.java)
    private val mapAdapter = moshi.adapter<Map<String, Any?>>(
        Types.newParameterizedType(Map::class.java, String::class.java, Any::class.java),
    )

    suspend fun submitFollowup(payload: FollowupApprovalRequest, attachments: List<Uri> = emptyList()): QueuedSubmission<ApprovalSummary> {
        val approval = try {
            api.createFollowup(payload)
        } catch (error: Throwable) {
            if (!NetworkFailurePolicy.isRetryable(error)) throw error
            val operationId = sync.enqueue(
                actionType = if (payload.followup.needSupport) "support.create" else "followup.create",
                resourceType = "crm_project_customer_task",
                resourceId = payload.followup.taskId.toString(),
                baseUpdatedAt = null,
                payload = mapAdapter.fromJson(followupAdapter.toJson(payload)).orEmpty(),
            )
            sync.queueAttachments(operationId, attachments)
            return QueuedSubmission(queued = true, operationId = operationId, attachmentsPending = attachments.isNotEmpty())
        }
        val uploaded = sync.queueAndUploadApprovalAttachments(approval.id, attachments)
        return QueuedSubmission(value = approval, attachmentsPending = attachments.isNotEmpty() && !uploaded)
    }

    suspend fun saveCustomerProfile(
        customerCode: String,
        changes: Map<String, String?>,
        baseValues: Map<String, String?>,
        baseUpdatedAt: String?,
    ): QueuedSubmission<CustomerProfileUpdateResult> {
        val json = JSONObject()
        changes.forEach { (key, value) -> json.put(key, value ?: JSONObject.NULL) }
        return try {
            QueuedSubmission(
                value = api.updateCustomerProfile(
                    customerCode,
                    json.toString().toRequestBody("application/json; charset=utf-8".toMediaType()),
                )
            )
        } catch (error: Throwable) {
            if (!NetworkFailurePolicy.isRetryable(error)) throw error
            val operationId = sync.enqueue(
                actionType = "customer_profile.patch",
                resourceType = "customer_master",
                resourceId = customerCode,
                baseUpdatedAt = baseUpdatedAt,
                payload = mapOf(
                    "customer_code" to customerCode,
                    "changes" to changes,
                    "base_values" to baseValues,
                ),
            )
            QueuedSubmission(queued = true, operationId = operationId)
        }
    }

    suspend fun saveBusinessProfile(customerCode: String, payload: BusinessProfileUpdateRequest): BusinessProfileUpdateResult =
        api.updateBusinessProfile(customerCode, payload)

    suspend fun workItems(offset: Int = 0): WorkItemPage = api.workItems(offset = offset)

    suspend fun resolveWorkItem(itemId: Long, note: String?, close: Boolean = false): WorkItemRow =
        api.workItemAction(itemId, if (close) "close" else "resolve", WorkItemActionPayload(note))

    suspend fun approvals(scope: String, mode: String, offset: Int = 0): ApprovalPage =
        api.approvals(scope = scope, mode = mode, offset = offset)

    suspend fun approval(approvalId: Long): ApprovalDetailEnvelope = api.approvalDetail(approvalId)

    suspend fun approvalAction(approvalId: Long, action: String, comment: String?): ApprovalDetailEnvelope =
        api.approvalAction(approvalId, action, ApprovalActionPayload(comment))

    suspend fun loadDraft(type: String, resourceId: String): String? = drafts.find(type, resourceId)?.contentJson

    suspend fun saveDraft(type: String, resourceId: String, json: String) =
        drafts.save(FormDraftEntity(type, resourceId, json))

    suspend fun clearDraft(type: String, resourceId: String) = drafts.delete(type, resourceId)
}
