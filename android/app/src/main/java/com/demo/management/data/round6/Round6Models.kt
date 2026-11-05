package com.demo.management.data.round6

import com.demo.management.core.sync.OfflineCachePolicy
import com.demo.management.core.sync.OutboxPolicy
import com.demo.management.data.local.OfflineLeadEntity
import com.squareup.moshi.Json
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin

data class LeadPage(
    val items: List<LeadRow> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
)

data class LeadRow(
    val id: Long,
    @Json(name = "lead_no") val leadNo: String,
    @Json(name = "lead_name") val leadName: String,
    @Json(name = "company_name") val companyName: String? = null,
    @Json(name = "contact_name") val contactName: String? = null,
    @Json(name = "contact_phone") val contactPhone: String? = null,
    val source: String? = null,
    @Json(name = "campaign_id") val campaignId: Long? = null,
    val region: String? = null,
    @Json(name = "business_line") val businessLine: String? = null,
    @Json(name = "intent_summary") val intentSummary: String? = null,
    val status: String,
    val priority: String = "normal",
    @Json(name = "pool_status") val poolStatus: String = "private",
    @Json(name = "qualification_note") val qualificationNote: String? = null,
    @Json(name = "owner_user_id") val ownerUserId: Long? = null,
    @Json(name = "assigned_user_id") val assignedUserId: Long? = null,
    @Json(name = "assigned_at") val assignedAt: String? = null,
    @Json(name = "assignment_expires_at") val assignmentExpiresAt: String? = null,
    @Json(name = "first_response_due_at") val firstResponseDueAt: String? = null,
    @Json(name = "first_responded_at") val firstRespondedAt: String? = null,
    @Json(name = "last_activity_at") val lastActivityAt: String? = null,
    @Json(name = "last_followup_at") val lastFollowupAt: String? = null,
    @Json(name = "next_followup_at") val nextFollowupAt: String? = null,
    @Json(name = "recycled_at") val recycledAt: String? = null,
    @Json(name = "recycle_count") val recycleCount: Int = 0,
    @Json(name = "current_approval_id") val currentApprovalId: Long? = null,
    @Json(name = "current_approval_status") val currentApprovalStatus: String? = null,
    @Json(name = "converted_customer_code") val convertedCustomerCode: String? = null,
    @Json(name = "converted_at") val convertedAt: String? = null,
    @Json(name = "converted_by_user_id") val convertedByUserId: Long? = null,
    @Json(name = "created_by_user_id") val createdByUserId: Long? = null,
    @Json(name = "updated_by_user_id") val updatedByUserId: Long? = null,
    @Json(name = "created_at") val createdAt: String? = null,
    @Json(name = "updated_at") val updatedAt: String? = null,
    @Json(name = "product_intents") val productIntents: List<LeadProductIntent> = emptyList(),
    val followups: List<LeadFollowup> = emptyList(),
    val assignments: List<LeadAssignmentEvent> = emptyList(),
)

data class LeadProductIntent(
    val id: Long? = null,
    @Json(name = "lead_id") val leadId: Long? = null,
    @Json(name = "product_code") val productCode: String? = null,
    @Json(name = "product_name") val productName: String,
    @Json(name = "quantity_note") val quantityNote: String? = null,
    @Json(name = "interest_level") val interestLevel: String? = null,
    val note: String? = null,
    @Json(name = "sort_order") val sortOrder: Int = 0,
)

data class LeadCreate(
    @Json(name = "lead_no") val leadNo: String? = null,
    @Json(name = "lead_name") val leadName: String,
    @Json(name = "company_name") val companyName: String? = null,
    @Json(name = "contact_name") val contactName: String? = null,
    @Json(name = "contact_phone") val contactPhone: String? = null,
    val source: String? = null,
    val region: String? = null,
    @Json(name = "business_line") val businessLine: String? = null,
    @Json(name = "intent_summary") val intentSummary: String? = null,
    val status: String = "new",
    @Json(name = "qualification_note") val qualificationNote: String? = null,
    @Json(name = "owner_user_id") val ownerUserId: Long? = null,
    @Json(name = "assigned_user_id") val assignedUserId: Long? = null,
    @Json(name = "next_followup_at") val nextFollowupAt: String? = null,
    @Json(name = "product_intents") val productIntents: List<LeadProductIntent> = emptyList(),
)

data class LeadUpdate(
    @Json(name = "lead_name") val leadName: String? = null,
    @Json(name = "company_name") val companyName: String? = null,
    @Json(name = "contact_name") val contactName: String? = null,
    @Json(name = "contact_phone") val contactPhone: String? = null,
    val source: String? = null,
    val region: String? = null,
    @Json(name = "business_line") val businessLine: String? = null,
    @Json(name = "intent_summary") val intentSummary: String? = null,
    val status: String? = null,
    @Json(name = "qualification_note") val qualificationNote: String? = null,
    @Json(name = "owner_user_id") val ownerUserId: Long? = null,
    @Json(name = "assigned_user_id") val assignedUserId: Long? = null,
    @Json(name = "next_followup_at") val nextFollowupAt: String? = null,
    @Json(name = "product_intents") val productIntents: List<LeadProductIntent>? = null,
)

data class LeadFollowup(
    val id: Long? = null,
    @Json(name = "lead_id") val leadId: Long? = null,
    @Json(name = "followup_no") val followupNo: String? = null,
    val content: String,
    val method: String? = null,
    val outcome: String? = null,
    @Json(name = "next_action") val nextAction: String? = null,
    @Json(name = "next_followup_at") val nextFollowupAt: String? = null,
    @Json(name = "created_by_user_id") val createdByUserId: Long? = null,
    @Json(name = "created_at") val createdAt: String? = null,
    @Json(name = "updated_at") val updatedAt: String? = null,
)

data class LeadAssignmentRequest(
    @Json(name = "assigned_user_id") val assignedUserId: Long? = null,
    val note: String? = null,
)

data class LeadAssignmentEvent(
    val id: Long,
    @Json(name = "lead_id") val leadId: Long,
    @Json(name = "event_type") val eventType: String = "assigned",
    @Json(name = "from_assignee_user_id") val fromAssigneeUserId: Long? = null,
    @Json(name = "to_assignee_user_id") val toAssigneeUserId: Long? = null,
    @Json(name = "assigned_by_user_id") val assignedByUserId: Long? = null,
    val note: String? = null,
    @Json(name = "created_at") val createdAt: String? = null,
)

data class LeadConversionApprovalRequest(
    val submit: Boolean = false,
    val priority: String = "normal",
    val note: String? = null,
)

data class LeadProjectPrefill(
    @Json(name = "customer_code") val customerCode: String,
    @Json(name = "customer_name") val customerName: String,
    @Json(name = "project_name") val projectName: String,
    @Json(name = "project_type") val projectType: String,
    @Json(name = "customer_scope_note") val customerScopeNote: String? = null,
    @Json(name = "business_line") val businessLine: String? = null,
    @Json(name = "owner_user_id") val ownerUserId: Long? = null,
    @Json(name = "source_lead_id") val sourceLeadId: Long,
    @Json(name = "source_lead_no") val sourceLeadNo: String,
)

data class LeadSlaSnapshot(
    val state: String = "normal",
    val phase: String? = null,
    val deadline: String? = null,
    @Json(name = "remaining_seconds") val remainingSeconds: Long? = null,
)

/** Strictly masked public-pool projection. Do not add contact, phone, address, or OCR fields. */
data class LeadPublicPoolRow(
    val id: Long,
    @Json(name = "lead_no") val leadNo: String,
    @Json(name = "lead_name") val leadName: String,
    @Json(name = "company_name") val companyName: String? = null,
    val source: String? = null,
    val region: String? = null,
    @Json(name = "business_line") val businessLine: String? = null,
    val priority: String = "normal",
    @Json(name = "pool_status") val poolStatus: String = "public",
    val status: String,
    @Json(name = "first_response_due_at") val firstResponseDueAt: String? = null,
    @Json(name = "recycled_at") val recycledAt: String? = null,
    @Json(name = "recycle_count") val recycleCount: Int = 0,
    @Json(name = "created_at") val createdAt: String? = null,
    val sla: LeadSlaSnapshot = LeadSlaSnapshot(),
)

data class LeadPublicPoolPage(
    val items: List<LeadPublicPoolRow> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
)

data class LeadSlaException(
    val lead: LeadRow,
    val sla: LeadSlaSnapshot,
)

data class LeadSlaExceptionPage(
    val items: List<LeadSlaException> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
)

data class LeadRecycleRequest(val note: String? = null)

fun canUseCustomerDevelopment(permissions: Collection<String>, featureFlags: Map<String, Boolean>): Boolean =
    featureFlags["lead_pool"] == true && "crm_lead.view" in permissions

object LeadCachePolicy {
    fun canRead(lastSyncedAt: Long?, now: Long = System.currentTimeMillis()): Boolean =
        OfflineCachePolicy.canRead(lastSyncedAt, now)

    fun freshRows(rows: List<OfflineLeadEntity>, now: Long = System.currentTimeMillis()): List<OfflineLeadEntity> =
        rows.filter { canRead(it.syncedAt, now) }

    fun freshRow(row: OfflineLeadEntity?, now: Long = System.currentTimeMillis()): OfflineLeadEntity? =
        row?.takeIf { canRead(it.syncedAt, now) }
}

object LeadOfflinePolicy {
    fun isEnabled(featureFlags: Map<String, Boolean>): Boolean =
        featureFlags["lead_pool"] == true && featureFlags["lead_offline"] == true

    /** Public-pool rows and other users' leads must never enter encrypted Room. */
    fun eligibleRowsForCache(rows: List<LeadRow>, currentUserId: Long): List<LeadRow> = rows.filter { lead ->
        lead.poolStatus == "private" && (lead.ownerUserId == currentUserId || lead.assignedUserId == currentUserId)
    }
}

object LeadOutboxPolicy {
    const val FOLLOWUP_ACTION_TYPE = "crm_lead_followup_create"

    fun canQueueFollowup(leadId: Long): Boolean = leadId > 0
    fun shouldRetry(actionType: String, leadId: Long, status: String): Boolean =
        actionType == FOLLOWUP_ACTION_TYPE && canQueueFollowup(leadId) && OutboxPolicy.shouldSend(status)

    fun newLeadActionType(): String? = null
}

object LeadDraftPolicy {
    const val NEW_LEAD_DRAFT_TYPE = "crm_lead_new"

    suspend fun clearAfterAutosave(autosave: Job?, clear: suspend () -> Unit) {
        autosave?.cancelAndJoin()
        clear()
    }
}

fun offlineLeadPage(
    rows: List<LeadRow>,
    query: String? = null,
    status: String? = null,
    source: String? = null,
    region: String? = null,
    assignedUserId: Long? = null,
    offset: Int = 0,
    limit: Int = 20,
): LeadPage {
    val keyword = query.orEmpty().trim().lowercase()
    val filtered = rows.filter { lead ->
        (status.isNullOrBlank() || lead.status == status) &&
            (source.isNullOrBlank() || lead.source == source) &&
            (region.isNullOrBlank() || lead.region == region) &&
            (assignedUserId == null || lead.assignedUserId == assignedUserId) &&
            (keyword.isBlank() || listOf(lead.leadNo, lead.leadName, lead.companyName, lead.contactName, lead.contactPhone, lead.source, lead.region)
                .any { it.orEmpty().lowercase().contains(keyword) })
    }
    return LeadPage(filtered.drop(offset).take(limit), filtered.size, limit, offset)
}

fun LeadRow.toOfflineEntity(payloadJson: String, syncedAt: Long): OfflineLeadEntity = OfflineLeadEntity(
    id = id,
    leadName = leadName,
    status = status,
    payloadJson = payloadJson,
    cacheScope = if (assignedUserId != null) "assigned" else "owned",
    remoteUpdatedAt = updatedAt,
    syncedAt = syncedAt,
)
