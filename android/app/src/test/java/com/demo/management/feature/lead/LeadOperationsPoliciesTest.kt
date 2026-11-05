package com.demo.management.feature.lead

import com.demo.management.data.round6.LeadOfflinePolicy
import com.demo.management.data.round6.LeadRow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LeadOperationsPoliciesTest {
    private val baseFlags = mapOf("lead_pool" to true)

    @Test
    fun workbenchSectionsRequireTheirOwnFlagAndPermission() {
        assertTrue(canOpenLeadOperationsWorkbench(setOf("crm_lead.view"), baseFlags))
        assertTrue(canViewLeadOperationsSection(LeadOperationsSection.Mine, setOf("crm_lead.view"), baseFlags))
        assertTrue(
            canViewLeadOperationsSection(
                LeadOperationsSection.ClaimablePool,
                setOf("crm_lead.view", "crm_lead.claim"),
                baseFlags + ("lead_public_pool" to true),
            ),
        )
        assertTrue(
            canViewLeadOperationsSection(
                LeadOperationsSection.DueSoon,
                setOf("crm_lead.view"),
                baseFlags + ("lead_sla" to true),
            ),
        )
        assertFalse(canViewLeadOperationsSection(LeadOperationsSection.ClaimablePool, setOf("crm_lead.view"), baseFlags + ("lead_public_pool" to true)))
        assertFalse(canViewLeadOperationsSection(LeadOperationsSection.ClaimablePool, setOf("crm_lead.claim"), baseFlags + ("lead_public_pool" to true)))
        assertFalse(canViewLeadOperationsSection(LeadOperationsSection.DueSoon, setOf("crm_lead.view"), baseFlags))
    }

    @Test
    fun publicPoolAndSlaViewsAreAlwaysOnlineOnly() {
        assertFalse(LeadOperationsCachePolicy.canPersist(LeadOperationsSection.ClaimablePool))
        assertFalse(LeadOperationsCachePolicy.canPersist(LeadOperationsSection.DueSoon))
        assertFalse(LeadOperationsOutboxPolicy.canQueue("crm_lead_claim"))
        assertFalse(LeadOperationsOutboxPolicy.canQueue("crm_lead_recycle"))
        assertFalse(LeadOperationsOutboxPolicy.canQueue("crm_lead_campaign_update"))
        assertTrue(LeadOperationsOutboxPolicy.canQueue("crm_lead_followup_create"))
        assertTrue(LeadOperationsCachePolicy.canPersist(LeadOperationsSection.Mine))
    }

    @Test
    fun onlyCurrentUsersPrivateOwnedOrAssignedLeadsAreEligibleForOfflineCache() {
        val rows = listOf(
            lead(1, owner = 7, assignee = null, poolStatus = "private"),
            lead(2, owner = null, assignee = 7, poolStatus = "private"),
            lead(3, owner = 7, assignee = null, poolStatus = "public"),
            lead(4, owner = 8, assignee = 8, poolStatus = "private"),
        )

        assertEquals(listOf(1L, 2L), LeadOfflinePolicy.eligibleRowsForCache(rows, currentUserId = 7).map { it.id })
    }

    @Test
    fun slaLabelsAreBusinessReadable() {
        assertEquals("已逾期", leadSlaStateLabel("overdue"))
        assertEquals("即将到期", leadSlaStateLabel("due_soon"))
        assertEquals("待分配", leadSlaStateLabel("unassigned"))
        assertEquals("正常", leadSlaStateLabel("normal"))
    }

    private fun lead(id: Long, owner: Long?, assignee: Long?, poolStatus: String) = LeadRow(
        id = id,
        leadNo = "LEAD-$id",
        leadName = "线索$id",
        status = "active",
        ownerUserId = owner,
        assignedUserId = assignee,
        poolStatus = poolStatus,
    )
}
