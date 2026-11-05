package com.demo.management.data.round6

import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.core.sync.NetworkFailurePolicy
import com.demo.management.data.QueuedSubmission
import com.demo.management.data.SyncRepository
import com.demo.management.data.local.FormDraftDao
import com.demo.management.data.local.FormDraftEntity
import com.demo.management.data.local.OfflineDao
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class Round6Repository @Inject constructor(
    private val api: Round6Api,
    private val offline: OfflineDao,
    private val drafts: FormDraftDao,
    private val sync: SyncRepository,
    moshi: Moshi,
) {
    @Volatile
    var lastReadWasOffline: Boolean = false
        private set

    private val leadAdapter = moshi.adapter(LeadRow::class.java)
    private val leadCreateAdapter = moshi.adapter(LeadCreate::class.java)
    private val followupAdapter = moshi.adapter(LeadFollowup::class.java)
    private val mapAdapter = moshi.adapter<Map<String, Any?>>(
        Types.newParameterizedType(Map::class.java, String::class.java, Any::class.java),
    )

    suspend fun leads(
        query: String? = null,
        status: String? = null,
        source: String? = null,
        region: String? = null,
        assignedUserId: Long? = null,
        limit: Int = 20,
        offset: Int = 0,
    ): LeadPage = runCatching {
        api.leads(query?.takeIf { it.isNotBlank() }, status, source, region, assignedUserId, limit, offset)
            .also { lastReadWasOffline = false }
    }.getOrElse { error ->
        if (!NetworkFailurePolicy.isRetryable(error) || !sync.canReadLeadCache()) throw error
        lastReadWasOffline = true
        offlineLeadPage(
            rows = LeadCachePolicy.freshRows(offline.leads()).mapNotNull { leadAdapter.fromJson(it.payloadJson) },
            query = query,
            status = status,
            source = source,
            region = region,
            assignedUserId = assignedUserId,
            offset = offset,
            limit = limit,
        )
    }

    suspend fun lead(leadId: Long): LeadRow = runCatching { api.lead(leadId).also { lastReadWasOffline = false } }
        .getOrElse { error ->
            if (!NetworkFailurePolicy.isRetryable(error) || !sync.canReadLeadCache()) throw error
            lastReadWasOffline = true
            LeadCachePolicy.freshRow(offline.lead(leadId))?.payloadJson?.let(leadAdapter::fromJson) ?: throw error
        }

    /** Public-pool responses are intentionally online-only and never fall back to Room. */
    suspend fun publicPool(
        query: String? = null,
        source: String? = null,
        region: String? = null,
        priority: String? = null,
        limit: Int = 20,
        offset: Int = 0,
    ): LeadPublicPoolPage = api.publicPool(query?.takeIf { it.isNotBlank() }, source, region, priority, limit, offset)
        .also { lastReadWasOffline = false }

    /** SLA exceptions are operationally sensitive and must be refreshed from the server. */
    suspend fun slaExceptions(
        state: String? = null,
        todayOnly: Boolean = false,
        limit: Int = 20,
        offset: Int = 0,
    ): LeadSlaExceptionPage =
        api.slaExceptions(state, todayOnly, limit, offset).also { lastReadWasOffline = false }

    suspend fun createLead(payload: LeadCreate): LeadRow = api.createLead(payload)

    suspend fun updateLead(leadId: Long, payload: LeadUpdate): LeadRow = api.updateLead(leadId, payload)

    suspend fun closeLead(leadId: Long): Map<String, Any?> = api.closeLead(leadId)

    suspend fun assignLead(leadId: Long, payload: LeadAssignmentRequest): LeadRow = api.assignLead(leadId, payload)

    suspend fun claimLead(leadId: Long): LeadRow = api.claimLead(leadId)

    suspend fun recycleLead(leadId: Long, note: String? = null): LeadRow = api.recycleLead(leadId, LeadRecycleRequest(note))

    suspend fun submitFollowup(leadId: Long, payload: LeadFollowup): QueuedSubmission<LeadFollowup> {
        require(LeadOutboxPolicy.canQueueFollowup(leadId)) { "离线跟进必须关联已存在的服务端线索" }
        val operationId = sync.enqueue(
            actionType = LeadOutboxPolicy.FOLLOWUP_ACTION_TYPE,
            resourceType = "crm_lead",
            resourceId = leadId.toString(),
            baseUpdatedAt = null,
            payload = mapAdapter.fromJson(followupAdapter.toJson(payload)).orEmpty(),
        )
        return try {
            val result = sync.submit(operationId)
                ?: error("已保存的线索跟进操作不存在")
            when (result.status) {
                "applied" -> QueuedSubmission(
                    value = followupAdapter.fromJson(mapAdapter.toJson(result.result.orEmpty()))
                        ?: error("线索跟进同步结果无效"),
                    operationId = operationId,
                )
                "processing", "retryable_error" -> QueuedSubmission(queued = true, operationId = operationId)
                else -> error(result.error?.get("message")?.toString() ?: "线索跟进同步失败")
            }
        } catch (error: Throwable) {
            if (!NetworkFailurePolicy.isRetryable(error)) throw error
            QueuedSubmission(queued = true, operationId = operationId)
        }
    }

    suspend fun saveNewLeadDraft(draftId: String, payload: LeadCreate) {
        drafts.save(FormDraftEntity(LeadDraftPolicy.NEW_LEAD_DRAFT_TYPE, draftId, leadCreateAdapter.toJson(payload)))
    }

    suspend fun loadNewLeadDraft(draftId: String): LeadCreate? =
        drafts.find(LeadDraftPolicy.NEW_LEAD_DRAFT_TYPE, draftId)?.contentJson?.let(leadCreateAdapter::fromJson)

    suspend fun clearNewLeadDraft(draftId: String) = drafts.delete(LeadDraftPolicy.NEW_LEAD_DRAFT_TYPE, draftId)

    suspend fun duplicateCheck(leadName: String?, contactPhone: String?, excludeLeadId: Long? = null): Map<String, Any?> =
        api.duplicateCheck(leadName, contactPhone, excludeLeadId)

    suspend fun summary(): Map<String, Any?> = api.summary()
    suspend fun dimensions(): Map<String, Any?> = api.dimensions()
    suspend fun analytics(): Map<String, Any?> = api.analytics()
    suspend fun projectPrefill(leadId: Long): LeadProjectPrefill = api.projectPrefill(leadId)
    suspend fun createConversionApproval(leadId: Long, payload: LeadConversionApprovalRequest): Map<String, Any?> =
        api.createConversionApproval(leadId, payload)

    fun errorMessage(error: Throwable): String = leadRepositoryErrorMessage(error)
}

fun leadRepositoryErrorMessage(error: Throwable): String = ApiErrorMapper.fromThrowable(error)
