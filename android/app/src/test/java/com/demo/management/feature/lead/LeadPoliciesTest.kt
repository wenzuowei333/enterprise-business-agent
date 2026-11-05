package com.demo.management.feature.lead

import com.demo.management.data.round6.LeadProjectPrefill
import com.demo.management.data.round6.LeadDraftPolicy
import com.demo.management.data.round6.LeadProductIntent
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withContext
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LeadPoliciesTest {
    private val viewPermissions = setOf("crm_lead.view")

    @Test
    fun entryRequiresLeadPoolFlagAndViewPermission() {
        assertTrue(canOpenLeadWorkspace(viewPermissions, mapOf("lead_pool" to true)))
        assertFalse(canOpenLeadWorkspace(viewPermissions, emptyMap()))
        assertFalse(canOpenLeadWorkspace(emptySet(), mapOf("lead_pool" to true)))
    }

    @Test
    fun actionsRequireTheirPermissionAndFeatureFlag() {
        assertTrue(canCreateLead(setOf("crm_lead.create"), mapOf("lead_pool" to true)))
        assertTrue(canUseLeadOcr(setOf("crm_lead.create"), mapOf("lead_pool" to true, "lead_ocr" to true)))
        assertTrue(canConvertLead(setOf("crm_lead.convert"), mapOf("lead_pool" to true, "lead_conversion" to true)))
        assertFalse(canUseLeadOcr(setOf("crm_lead.create"), mapOf("lead_pool" to true)))
        assertFalse(canConvertLead(setOf("crm_lead.convert"), mapOf("lead_pool" to true)))
    }

    @Test
    fun queuedFollowupRequiresLeadPoolOfflineFlagAndEditPermission() {
        assertTrue(canQueueLeadFollowup(setOf("crm_lead.edit"), mapOf("lead_pool" to true, "lead_offline" to true)))
        assertFalse(canQueueLeadFollowup(setOf("crm_lead.edit"), mapOf("lead_pool" to false, "lead_offline" to true)))
        assertFalse(canQueueLeadFollowup(setOf("crm_lead.edit"), mapOf("lead_pool" to true, "lead_offline" to false)))
        assertFalse(canQueueLeadFollowup(emptySet(), mapOf("lead_pool" to true, "lead_offline" to true)))
    }

    @Test
    fun formFeaturesRequireLeadPoolAndRespectEachExplicitFlag() {
        val permissions = setOf("crm_lead.create", "crm_lead.edit")

        assertEquals(
            LeadFormFeatures(productIntentsEnabled = false, offlineDraftsEnabled = true),
            leadFormFeatures(permissions, mapOf("lead_pool" to true, "lead_product_intent" to false, "lead_offline" to true)),
        )
        assertEquals(
            LeadFormFeatures(productIntentsEnabled = true, offlineDraftsEnabled = false),
            leadFormFeatures(permissions, mapOf("lead_pool" to true, "lead_product_intent" to true, "lead_offline" to false)),
        )
        assertEquals(
            LeadFormFeatures(productIntentsEnabled = false, offlineDraftsEnabled = false),
            leadFormFeatures(permissions, mapOf("lead_pool" to false, "lead_product_intent" to true, "lead_offline" to true)),
        )
    }

    @Test
    fun disabledProductIntentIsExcludedFromNewLeadPayload() {
        val payload = newLeadPayload(
            LeadFormSnapshot(
                leadName = "星河演示客户",
                source = "展会",
                productName = "工业泵",
                productNote = "现场演示后跟进",
            ),
            productIntentsEnabled = false,
        )

        assertEquals("new", payload.status)
        assertEquals(emptyList<LeadProductIntent>(), payload.productIntents)
    }

    @Test
    fun serverLeadStatesUseNewAndNeverExposeLost() {
        assertEquals("新建", leadStatusLabel("new"))
        assertEquals("已关闭", leadStatusLabel("closed"))
        assertEquals("已驳回", leadStatusLabel("rejected"))
        assertFalse(leadStatusFilters().any { it.first == "lost" })
        assertFalse(canTransitionLead("new", "lost"))
    }

    @Test
    fun conversionRequiresQualifiedOrTerminalPriorApprovalForResubmission() {
        assertTrue(canRequestLeadConversion("qualified", null))
        assertTrue(canRequestLeadConversion("conversion_pending", "rejected"))
        assertTrue(canRequestLeadConversion("conversion_pending", "cancelled"))
        assertTrue(canRequestLeadConversion("conversion_pending", "completed"))
        assertFalse(canRequestLeadConversion("conversion_pending", "submitted"))
        assertFalse(canRequestLeadConversion("conversion_pending", null))
        assertFalse(canRequestLeadConversion("new", null))
    }

    @Test
    fun exactDuplicatesBlockOnlineLeadSubmission() {
        assertTrue(leadDuplicateDecision(mapOf("exact_matches" to listOf(mapOf("reason" to "phone")))).blocksSubmission)
        assertTrue(leadDuplicateDecision(mapOf("duplicates" to listOf(mapOf("match_type" to "exact_name")))).blocksSubmission)
        assertTrue(leadDuplicateDecision(mapOf("has_blocking_duplicates" to true, "items" to emptyList<Any>())).blocksSubmission)
        assertFalse(leadDuplicateDecision(mapOf("advisories" to listOf(mapOf("reason" to "fuzzy_name")))).blocksSubmission)
    }

    @Test
    fun statusTransitionsMatchServerEditableStatesAndRejectConversionLifecycleMoves() {
        assertTrue(canTransitionLead("new", "active"))
        assertTrue(canTransitionLead("active", "qualified"))
        assertTrue(canTransitionLead("qualified", "closed"))
        assertFalse(canTransitionLead("qualified", "conversion_pending"))
        assertFalse(canTransitionLead("conversion_pending", "qualified"))
        assertFalse(canTransitionLead("converted", "qualified"))
        assertFalse(canTransitionLead("new", "converted"))
    }

    @Test
    fun ocrCandidatesAreNeverPreselectedAndOnlyMapLeadFields() {
        val mapped = mapOcrFieldsForLead(
            mapOf("customer_name" to "星河演示", "name" to "张三", "phone" to "00000000000", "address" to "上海", "unknown" to "ignored"),
        )

        assertEquals(emptySet<String>(), defaultOcrSelection(mapped))
        assertEquals("星河演示", mapped.companyName)
        assertEquals("张三", mapped.contactName)
        assertEquals("00000000000", mapped.contactPhone)
        assertEquals("上海", mapped.region)
    }

    @Test
    fun ocrOnlyReplacesExistingLeadFieldsAfterOverwriteConfirmation() {
        val current = LeadOcrFields(companyName = "旧公司", contactPhone = "00000000000")
        val values = mapOf("customer_name" to "新公司", "contact_phone" to "00000000000", "contact_name" to "张三")

        val unconfirmed = applyOcrFieldsToLead(current, values, confirmedOverwrite = false)
        val confirmed = applyOcrFieldsToLead(current, values, confirmedOverwrite = true)

        assertEquals("旧公司", unconfirmed.companyName)
        assertEquals("00000000000", unconfirmed.contactPhone)
        assertEquals("张三", unconfirmed.contactName)
        assertEquals("新公司", confirmed.companyName)
        assertEquals("00000000000", confirmed.contactPhone)
    }

    @Test
    fun leadReminderDeepLinkPreservesTheLeadId() {
        assertEquals("lead/42", leadDeepLink("42"))
        assertEquals("lead/42", leadDeepLink("42:2026-07-12T09:00:00+00:00"))
        assertNull(leadDeepLink(null))
        assertNull(leadDeepLink("not-a-number"))
    }

    @Test
    fun projectHandoffRequiresProjectCreatePermissionAndFeature() {
        assertTrue(canOpenProjectApplication(setOf("crm_project.create"), mapOf("project_application" to true)))
        assertFalse(canOpenProjectApplication(emptySet(), mapOf("project_application" to true)))
        assertFalse(canOpenProjectApplication(setOf("crm_project.create"), emptyMap()))
    }

    @Test
    fun completedSubmissionClearsTheDraftAfterAnInFlightAutosave() = runTest {
        var draft = "fresh"
        val autosave = backgroundScope.launch {
            try {
                awaitCancellation()
            } finally {
                withContext(NonCancellable) { draft = "stale" }
            }
        }

        LeadDraftPolicy.clearAfterAutosave(autosave) { draft = "" }

        assertEquals("", draft)
    }

    @Test
    fun staleLeadListResponsesAreRejectedWhenTheFilterGenerationChanges() {
        val request = LeadListRequest(generation = 3, requestId = 8, query = "旧筛选", status = "draft", offset = 20)

        assertTrue(acceptsLeadListResponse(request, activeGeneration = 3, activeRequestId = 8))
        assertFalse(acceptsLeadListResponse(request, activeGeneration = 4, activeRequestId = 9))
    }

    @Test
    fun conversionPrefillCreatesCustomerSelectionWithoutCreatingProject() {
        val result = projectPrefillForConvertedLead(
            LeadProjectPrefill(
                customerCode = "KHCRM20260712000042",
                customerName = "星河演示客户",
                projectName = "客户开发项目",
                projectType = "客户项目",
                sourceLeadId = 42,
                sourceLeadNo = "LD42",
            ),
        )

        assertEquals("KHCRM20260712000042", result.customerCode)
        assertEquals("星河演示客户", result.customerName)
        assertFalse(result.autoCreateProject)
    }
}
