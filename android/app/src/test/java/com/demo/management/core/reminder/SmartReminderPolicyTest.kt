package com.demo.management.core.reminder

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SmartReminderPolicyTest {
    @Test
    fun reminderKeyIsStableForSameBusinessDeadline() {
        assertEquals(
            reminderIdentity("next_followup", "task-12", "2026-07-20T09:00:00Z"),
            reminderIdentity("next_followup", "task-12", "2026-07-20T09:00:00Z"),
        )
    }

    @Test
    fun completedAndDuplicateRulesAreNotScheduled() {
        val first = LocalReminderRule("task", "12", "2026-07-20T09:00:00Z", completed = false)
        val duplicate = first.copy()
        val completed = LocalReminderRule("task", "13", "2026-07-20T09:00:00Z", completed = true)

        val result = deduplicateActiveReminders(listOf(first, duplicate, completed))

        assertEquals(1, result.size)
        assertFalse(result.single().completed)
    }

    @Test
    fun aiDraftVisibilityRequiresAdminAndFlag() {
        assertTrue(canUseAiDrafts("admin", mapOf("ai_drafts" to true)))
        assertFalse(canUseAiDrafts("salesperson", mapOf("ai_drafts" to true)))
        assertFalse(canUseAiDrafts("admin", mapOf("ai_drafts" to false)))
    }
}
