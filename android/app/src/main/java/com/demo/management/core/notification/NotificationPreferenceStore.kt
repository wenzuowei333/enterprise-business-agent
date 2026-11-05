package com.demo.management.core.notification

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import androidx.core.app.NotificationManagerCompat
import com.demo.management.core.reminder.reminderIdentity
import com.demo.management.data.round3.MobileNotification

data class LocalNotificationPreferences(
    val approval: Boolean = true,
    val task: Boolean = true,
    val risk: Boolean = true,
)

@Singleton
class NotificationPreferenceStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val preferences = context.getSharedPreferences("mobile_notification_preferences", Context.MODE_PRIVATE)

    fun current(): LocalNotificationPreferences = LocalNotificationPreferences(
        approval = preferences.getBoolean("approval", true),
        task = preferences.getBoolean("task", true),
        risk = preferences.getBoolean("risk", true),
    )

    fun update(approval: Boolean, task: Boolean, risk: Boolean) {
        preferences.edit()
            .putBoolean("approval", approval)
            .putBoolean("task", task)
            .putBoolean("risk", risk)
            .apply()
    }

    fun allows(target: String): Boolean = current().let { current ->
        when (target) {
            "approvals" -> current.approval
            "tasks", "work_items" -> current.task
            else -> current.risk
        }
    }

    fun snooze(item: MobileNotification, durationMs: Long = 2 * 60 * 60 * 1000L) {
        val identity = item.reminderIdentity()
        preferences.edit().putLong("snooze_$identity", System.currentTimeMillis() + durationMs).apply()
        val shownStore = context.getSharedPreferences("mobile_notifications", Context.MODE_PRIVATE)
        val shown = shownStore.getStringSet("shown_ids", emptySet()).orEmpty().toMutableSet()
        shown.remove(identity)
        shownStore.edit().putStringSet("shown_ids", shown).apply()
        NotificationManagerCompat.from(context).cancel(identity.hashCode())
    }

    fun isSnoozed(item: MobileNotification, now: Long = System.currentTimeMillis()): Boolean {
        val key = "snooze_${item.reminderIdentity()}"
        val until = preferences.getLong(key, 0L)
        if (until <= now && until > 0L) preferences.edit().remove(key).apply()
        return until > now
    }
}

fun MobileNotification.reminderIdentity(): String = reminderIdentity(
    type = notificationType,
    resourceId = sourceId ?: taskId?.toString() ?: projectId?.toString() ?: notificationId,
    dueAt = dueAt ?: createdAt.orEmpty(),
)
