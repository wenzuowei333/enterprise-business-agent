package com.demo.management.data.round6

import com.demo.management.data.local.OfflineLeadEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.http.GET
import retrofit2.http.POST
import java.net.UnknownHostException

class Round6RepositoryTest {
    @Test
    fun customerDevelopmentRequiresLeadPoolFlagAndViewPermission() {
        assertTrue(canUseCustomerDevelopment(setOf("crm_lead.view"), mapOf("lead_pool" to true)))
        assertFalse(canUseCustomerDevelopment(emptySet(), mapOf("lead_pool" to true)))
        assertFalse(canUseCustomerDevelopment(setOf("crm_lead.view"), mapOf("lead_pool" to false)))
    }

    @Test
    fun leadCacheExpiresAfterTwentyFourHours() {
        val now = 1_000_000_000L
        assertTrue(LeadCachePolicy.canRead(now - 23 * 60 * 60 * 1000L, now))
        assertFalse(LeadCachePolicy.canRead(now - 25 * 60 * 60 * 1000L, now))
    }

    @Test
    fun offlineLeadCacheFiltersExpiryPerEntityAndNeverReturnsStaleRows() {
        val now = 1_000_000_000L
        val fresh = OfflineLeadEntity(1, "南京新材料", "active", "{\"id\":1}", syncedAt = now - 23 * 60 * 60 * 1000L)
        val stale = OfflineLeadEntity(2, "过期线索", "active", "{\"id\":2}", syncedAt = now - 25 * 60 * 60 * 1000L)

        assertEquals(listOf(fresh), LeadCachePolicy.freshRows(listOf(fresh, stale), now))
        assertNull(LeadCachePolicy.freshRow(stale, now))
    }

    @Test
    fun offlineLeadCacheRequiresBothBootstrapFlags() {
        assertTrue(LeadOfflinePolicy.isEnabled(mapOf("lead_pool" to true, "lead_offline" to true)))
        assertFalse(LeadOfflinePolicy.isEnabled(mapOf("lead_pool" to false, "lead_offline" to true)))
        assertFalse(LeadOfflinePolicy.isEnabled(mapOf("lead_pool" to true, "lead_offline" to false)))
    }

    @Test
    fun offlineLeadPageFiltersThenPaginates() {
        val leads = listOf(
            lead(id = 1, leadName = "苏州纺织", status = "active"),
            lead(id = 2, leadName = "杭州纺织", status = "qualified"),
            lead(id = 3, leadName = "上海机械", status = "active"),
        )

        val page = offlineLeadPage(leads, query = "纺织", status = null, offset = 1, limit = 1)

        assertEquals(2, page.total)
        assertEquals(listOf(2L), page.items.map { it.id })
        assertEquals(1, page.offset)
    }

    @Test
    fun offlineLeadPageHonorsSourceRegionAndAssigneeScope() {
        val leads = listOf(
            lead(id = 1, leadName = "苏州纺织", status = "active", source = "展会", region = "华东", assignedUserId = 9),
            lead(id = 2, leadName = "杭州纺织", status = "active", source = "转介绍", region = "华东", assignedUserId = 9),
            lead(id = 3, leadName = "宁波纺织", status = "active", source = "展会", region = "华东", assignedUserId = 8),
        )

        val page = offlineLeadPage(leads, source = "展会", region = "华东", assignedUserId = 9)

        assertEquals(listOf(1L), page.items.map { it.id })
    }

    @Test
    fun onlyExistingServerLeadsCanBeQueuedForOfflineFollowup() {
        assertTrue(LeadOutboxPolicy.canQueueFollowup(42))
        assertFalse(LeadOutboxPolicy.canQueueFollowup(0))
        assertFalse(LeadOutboxPolicy.canQueueFollowup(-1))
    }

    @Test
    fun onlyRetryableExistingLeadFollowupsAreReturnedToTheOutbox() {
        assertTrue(LeadOutboxPolicy.shouldRetry(LeadOutboxPolicy.FOLLOWUP_ACTION_TYPE, 42, "retryable_error"))
        assertFalse(LeadOutboxPolicy.shouldRetry(LeadOutboxPolicy.FOLLOWUP_ACTION_TYPE, 0, "retryable_error"))
        assertFalse(LeadOutboxPolicy.shouldRetry("crm_lead_create", 42, "retryable_error"))
        assertFalse(LeadOutboxPolicy.shouldRetry("crm_lead_followup_create", 42, "conflict"))
    }

    @Test
    fun newLeadDraftsUseFormDraftWithoutAnOutboxAction() {
        assertEquals("crm_lead_new", LeadDraftPolicy.NEW_LEAD_DRAFT_TYPE)
        assertNull(LeadOutboxPolicy.newLeadActionType())
    }

    @Test
    fun syncLeadMapsToEncryptedRoomRowWithoutLosingRemoteVersion() {
        val row = lead(id = 8, leadName = "宁波新材料", status = "active", updatedAt = "2026-07-12T00:00:00Z", assignedUserId = 7)

        val entity = row.toOfflineEntity(payloadJson = "{\"id\":8}", syncedAt = 99L)

        assertEquals(
            OfflineLeadEntity(
                id = 8,
                leadName = "宁波新材料",
                status = "active",
                payloadJson = "{\"id\":8}",
                cacheScope = "assigned",
                remoteUpdatedAt = "2026-07-12T00:00:00Z",
                syncedAt = 99L,
            ),
            entity,
        )
    }

    @Test
    fun retrofitContractUsesTheRoundSixMobileLeadRoutes() {
        assertEquals("mobile/leads", route("leads", GET::class.java))
        assertEquals("mobile/leads/{leadId}", route("lead", GET::class.java))
        assertEquals("mobile/leads/public-pool", route("publicPool", GET::class.java))
        assertEquals("mobile/leads/sla-exceptions", route("slaExceptions", GET::class.java))
        assertEquals("mobile/leads/{leadId}/claim", route("claimLead", POST::class.java))
        assertFalse(Round6Api::class.java.declaredMethods.any { it.name == "createFollowup" })
    }

    @Test
    fun repositoryMapsNetworkFailuresToTheExistingMobileMessage() {
        assertEquals("网络不可用，请检查网络连接", leadRepositoryErrorMessage(UnknownHostException()))
    }

    private fun route(name: String, annotation: Class<out Annotation>): String {
        val method = Round6Api::class.java.declaredMethods.single { it.name == name }
        return when (annotation) {
            GET::class.java -> requireNotNull(method.getAnnotation(GET::class.java)).value
            POST::class.java -> requireNotNull(method.getAnnotation(POST::class.java)).value
            else -> error("unsupported annotation")
        }
    }

    private fun lead(
        id: Long,
        leadName: String,
        status: String,
        updatedAt: String? = null,
        source: String? = null,
        region: String? = null,
        assignedUserId: Long? = null,
    ) = LeadRow(
        id = id,
        leadNo = "LEAD-$id",
        leadName = leadName,
        status = status,
        updatedAt = updatedAt,
        source = source,
        region = region,
        assignedUserId = assignedUserId,
    )
}
