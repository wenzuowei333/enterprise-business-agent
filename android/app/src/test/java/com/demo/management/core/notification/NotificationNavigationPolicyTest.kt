package com.demo.management.core.notification

import com.demo.management.data.round3.MobileNotification
import org.junit.Assert.assertEquals
import org.junit.Test

class NotificationNavigationPolicyTest {
    @Test
    fun routesNotificationsToTheirBusinessObject() {
        assertEquals("approvals", notificationTarget(notification("supplement", "approval", "81")))
        assertEquals("projects", notificationTarget(notification("overdue", "crm_task", "22")))
        assertEquals("work_items", notificationTarget(notification("support", "work_item", "7")))
        assertEquals("data", notificationTarget(notification("data_risk", "inventory_check", "3")))
        assertEquals("deliveries", notificationTarget(notification("delivery_exception", "delivery_task", "9")))
        assertEquals("exceptions", notificationTarget(notification("exception_risk", "exception_case", "EX-9")))
        assertEquals("approvals", notificationTarget(notification("customer_tag_review", "customer_tag_request", "12")))
    }

    @Test
    fun leadReminderWithCompositeSourceIdOpensTheLeadOnTheLeadChannel() {
        val reminder = notification("lead_followup", "crm_lead", "42:2026-07-12T09:00:00+00:00")

        assertEquals("lead/42", notificationTarget(reminder))
        assertEquals(NotificationSyncWorker.CHANNEL_LEAD, notificationChannel(reminder))
    }

    @Test
    fun actionPathRemainsACompatibleFallback() {
        assertEquals("approvals", notificationTarget(notification("unknown", "unknown", "1", "/crm/work")))
        assertEquals("deliveries", notificationTarget(notification("unknown", "unknown", "1", "/fulfillment?delivery_id=1")))
        assertEquals("exceptions", notificationTarget(notification("unknown", "unknown", "1", "/exceptions/EX-1")))
        assertEquals("notifications", notificationTarget(notification("unknown", "unknown", "1", null)))
    }

    private fun notification(type: String, sourceType: String, sourceId: String, actionPath: String? = null) = MobileNotification(
        notificationId = "$type:$sourceType:$sourceId",
        notificationType = type,
        title = "test",
        sourceType = sourceType,
        sourceId = sourceId,
        actionPath = actionPath,
    )
}
