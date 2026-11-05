package com.demo.management.core.sync

object OfflineCachePolicy {
    private const val MAX_AGE_MILLIS = 24L * 60L * 60L * 1000L

    fun canRead(lastSyncedAt: Long?, now: Long = System.currentTimeMillis()): Boolean =
        lastSyncedAt != null && now >= lastSyncedAt && now - lastSyncedAt <= MAX_AGE_MILLIS
}

object OutboxPolicy {
    private val onlineOnlyActionTypes = setOf(
        "crm_lead_claim",
        "crm_lead_recycle",
    )

    fun canQueue(actionType: String): Boolean =
        actionType !in onlineOnlyActionTypes && !actionType.startsWith("crm_lead_campaign_")

    fun shouldSend(status: String): Boolean = status == "pending" || status == "retryable_error"
}
