package com.demo.management.core.notification

import com.demo.management.data.round3.MobileNotification

class NotificationDeduplicator(private val shownIds: MutableSet<String>) {
    fun shouldShow(id: String): Boolean = shownIds.add(id)
}

private fun MobileNotification.deliveryIdentity(smartReminders: Boolean): String =
    if (smartReminders) reminderIdentity() else notificationId

fun activeNotificationIdentities(items: List<MobileNotification>, smartReminders: Boolean): Set<String> =
    items.asSequence()
        .filter { it.status == "pending" }
        .map { it.deliveryIdentity(smartReminders) }
        .toSet()

fun notificationDeliveryCandidates(
    items: List<MobileNotification>,
    shownIds: Set<String>,
    smartReminders: Boolean,
    limit: Int = 8,
): List<MobileNotification> = items.asSequence()
    .filter { it.status == "pending" }
    .filter { it.deliveryIdentity(smartReminders) !in shownIds }
    .take(limit)
    .toList()
