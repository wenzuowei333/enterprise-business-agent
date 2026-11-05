package com.demo.management.core.notification

import com.demo.management.data.round3.MobileNotification

fun notificationTarget(item: MobileNotification): String = when {
    item.sourceType == "crm_lead" || item.notificationType in setOf("lead_reminder", "lead_followup") -> leadDeepLink(item.sourceId) ?: "customer_development"
    item.sourceType == "delivery_task" || item.notificationType in setOf("delivery", "delivery_exception") -> "deliveries"
    item.sourceType == "exception_case" || item.notificationType in setOf("exception", "exception_risk") -> "exceptions"
    item.sourceType in setOf("customer_tag", "customer_tag_request") || item.notificationType == "customer_tag_review" -> "approvals"
    item.sourceType == "approval" || item.notificationType == "supplement" -> "approvals"
    item.sourceType == "crm_task" || item.notificationType in setOf("today", "overdue") -> "projects"
    item.sourceType == "work_item" || item.notificationType == "support" -> "work_items"
    item.sourceType in setOf("inventory_check", "receivable_check") || item.notificationType == "data_risk" -> "data"
    item.actionPath in setOf("/crm/work", "/crm/submissions") -> "approvals"
    item.actionPath == "/crm/tasks" -> "projects"
    item.actionPath == "/crm/issues" -> "work_items"
    item.actionPath?.startsWith("/fulfillment") == true -> "deliveries"
    item.actionPath?.startsWith("/exceptions") == true -> "exceptions"
    else -> "notifications"
}

fun notificationChannel(item: MobileNotification): String = when (notificationTarget(item)) {
    "approvals" -> NotificationSyncWorker.CHANNEL_APPROVAL
    "projects", "work_items", "deliveries" -> NotificationSyncWorker.CHANNEL_TASK
    else -> if (notificationTarget(item).startsWith("lead/")) NotificationSyncWorker.CHANNEL_LEAD else NotificationSyncWorker.CHANNEL_RISK
}

private fun leadDeepLink(sourceId: String?): String? = sourceId
    ?.substringBefore(':')
    ?.toLongOrNull()
    ?.takeIf { it > 0 }
    ?.let { "lead/$it" }
