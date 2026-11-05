package com.demo.management.core.notification

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import com.demo.management.data.round3.MobileNotification

class NotificationDeduplicatorTest {
    @Test
    fun sameBusinessNotificationIsOnlyShownOnce() {
        val deduplicator = NotificationDeduplicator(mutableSetOf())
        assertTrue(deduplicator.shouldShow("task:42"))
        assertFalse(deduplicator.shouldShow("task:42"))
        assertTrue(deduplicator.shouldShow("approval:42"))
    }

    @Test
    fun identityUsesBusinessObjectTypeAndDeadline() {
        val first = MobileNotification(
            notificationId = "server-a",
            notificationType = "next_followup",
            title = "跟进提醒",
            sourceId = "task-42",
            dueAt = "2026-07-20T09:00:00Z",
        )
        val duplicate = first.copy(notificationId = "server-b")
        val rescheduled = first.copy(notificationId = "server-c", dueAt = "2026-07-21T09:00:00Z")

        assertEquals(first.reminderIdentity(), duplicate.reminderIdentity())
        assertNotEquals(first.reminderIdentity(), rescheduled.reminderIdentity())
    }

    @Test
    fun batchLimitDoesNotMarkUnsentNotificationsAsShown() {
        val items = (1..10).map { index ->
            MobileNotification(
                notificationId = "task-$index",
                notificationType = "task_due",
                title = "任务 $index",
                sourceType = "task",
                sourceId = index.toString(),
            )
        }

        val first = notificationDeliveryCandidates(items, emptySet(), smartReminders = false, limit = 8)
        val shown = first.mapTo(mutableSetOf()) { it.notificationId }
        val second = notificationDeliveryCandidates(items, shown, smartReminders = false, limit = 8)

        assertEquals(8, first.size)
        assertEquals(listOf("task-9", "task-10"), second.map { it.notificationId })
    }

    @Test
    fun processedNotificationsAreNotActiveOrDeliverable() {
        val processed = MobileNotification(
            notificationId = "approval-1",
            notificationType = "approval",
            title = "已处理审批",
            status = "processed",
        )

        assertTrue(notificationDeliveryCandidates(listOf(processed), emptySet(), false).isEmpty())
        assertTrue(activeNotificationIdentities(listOf(processed), false).isEmpty())
    }
}
