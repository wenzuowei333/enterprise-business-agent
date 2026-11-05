package com.demo.management.core.sync

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OfflineCachePolicyTest {
    @Test
    fun cacheExpiresAfterTwentyFourHours() {
        val now = 1_000_000_000L
        assertTrue(OfflineCachePolicy.canRead(now - 23 * 60 * 60 * 1000L, now))
        assertFalse(OfflineCachePolicy.canRead(now - 25 * 60 * 60 * 1000L, now))
    }

    @Test
    fun onlyExplicitlySubmittedRetryableRowsAreSent() {
        assertTrue(OutboxPolicy.shouldSend("pending"))
        assertTrue(OutboxPolicy.shouldSend("retryable_error"))
        assertFalse(OutboxPolicy.shouldSend("draft"))
        assertFalse(OutboxPolicy.shouldSend("conflict"))
        assertFalse(OutboxPolicy.shouldSend("rejected"))
    }

    @Test
    fun onlineOnlyLeadOperationsCannotEnterTheOutbox() {
        assertFalse(OutboxPolicy.canQueue("crm_lead_claim"))
        assertFalse(OutboxPolicy.canQueue("crm_lead_recycle"))
        assertFalse(OutboxPolicy.canQueue("crm_lead_campaign_create"))
        assertTrue(OutboxPolicy.canQueue("crm_lead_followup_create"))
    }
}
