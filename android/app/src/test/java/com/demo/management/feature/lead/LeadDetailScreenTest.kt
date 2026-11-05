package com.demo.management.feature.lead

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LeadDetailScreenTest {
    @Test
    fun queuedFollowupControlIsVisibleAndAcceptedOnlyWhenEnabled() {
        assertTrue(canShowQueuedFollowupControl(canQueueFollowup = true))
        assertTrue(canAcceptLeadDetailAction("followup", canQueueFollowup = true))
        assertFalse(canShowQueuedFollowupControl(canQueueFollowup = false))
        assertFalse(canAcceptLeadDetailAction("followup", canQueueFollowup = false))
    }

    @Test
    fun disablingQueuedFollowupDoesNotBlockOtherDetailActions() {
        assertTrue(canAcceptLeadDetailAction("assign", canQueueFollowup = false))
        assertTrue(canAcceptLeadDetailAction("convert", canQueueFollowup = false))
    }
}
