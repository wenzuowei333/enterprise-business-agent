package com.demo.management.core.notification

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.demo.management.MainActivity
import com.demo.management.R
import com.demo.management.core.auth.TokenProvider
import com.demo.management.core.auth.SecureSessionStore
import com.demo.management.core.auth.hydrateTokenProvider
import com.demo.management.data.round3.MobileNotification
import com.demo.management.data.round3.ToolsRepository
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import java.time.LocalTime
import java.util.concurrent.TimeUnit
import com.demo.management.data.BootstrapPayload
import com.squareup.moshi.Moshi

@HiltWorker
class NotificationSyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val repository: ToolsRepository,
    private val tokenProvider: TokenProvider,
    private val sessionStore: SecureSessionStore,
    private val notificationPreferences: NotificationPreferenceStore,
    moshi: Moshi,
) : CoroutineWorker(context, params) {
    private val bootstrapAdapter = moshi.adapter(BootstrapPayload::class.java)

    override suspend fun doWork(): Result {
        if (tokenProvider.refreshToken().isNullOrBlank() && !hydrateTokenProvider(sessionStore.accessToken(), sessionStore.refreshToken(), tokenProvider)) return Result.success()
        return runCatching {
            val center = repository.notifications()
            val smartReminders = sessionStore.bootstrap()?.let { raw ->
                runCatching { bootstrapAdapter.fromJson(raw)?.app?.featureFlags?.get("smart_reminders") == true }.getOrDefault(false)
            } ?: false
            if (!isQuietHours()) showNewNotifications(center.items, smartReminders)
            Result.success()
        }.getOrElse { Result.retry() }
    }

    private fun showNewNotifications(items: List<MobileNotification>, smartReminders: Boolean) {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val preferences = applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val ids = preferences.getStringSet(SHOWN, emptySet()).orEmpty().toMutableSet()
        fun identity(item: MobileNotification) = if (smartReminders) item.reminderIdentity() else item.notificationId
        val eligibleItems = items
            .filter { notificationPreferences.allows(notificationTarget(it)) }
            .filterNot { smartReminders && notificationPreferences.isSnoozed(it) }
        val activeIdentities = activeNotificationIdentities(eligibleItems, smartReminders)
        (ids - activeIdentities).forEach { stale ->
            NotificationManagerCompat.from(applicationContext).cancel(stale.hashCode())
            ids.remove(stale)
        }
        notificationDeliveryCandidates(eligibleItems, ids, smartReminders, limit = 8)
            .forEach { item ->
            val identity = identity(item)
            val intent = Intent(applicationContext, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
                putExtra("target", targetRoute(item))
            }
            val pendingIntent = PendingIntent.getActivity(applicationContext, identity.hashCode(), intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            val notification = NotificationCompat.Builder(applicationContext, notificationChannel(item))
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(item.title)
                .setContentText(item.detail ?: "点击查看详情")
                .setStyle(NotificationCompat.BigTextStyle().bigText(item.detail ?: "点击查看详情"))
                .setPriority(if (item.priority == "high") NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT)
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
                .build()
            NotificationManagerCompat.from(applicationContext).notify(identity.hashCode(), notification)
            ids.add(identity)
        }
        preferences.edit().putStringSet(SHOWN, ids.toList().takeLast(300).toSet()).apply()
    }

    private fun isQuietHours(): Boolean {
        val hour = LocalTime.now().hour
        return hour >= 22 || hour < 8
    }

    private fun targetRoute(item: MobileNotification): String = notificationTarget(item)

    companion object {
        private const val PREFS = "mobile_notifications"
        private const val SHOWN = "shown_ids"
        const val CHANNEL_APPROVAL = "mobile_approval"
        const val CHANNEL_TASK = "mobile_task"
        const val CHANNEL_LEAD = "mobile_lead"
        const val CHANNEL_RISK = "mobile_risk"

        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<NotificationSyncWorker>(15, TimeUnit.MINUTES).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("mobile-notification-sync", ExistingPeriodicWorkPolicy.UPDATE, request)
        }

        fun createChannels(context: Context) {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannels(
                listOf(
                    NotificationChannel(CHANNEL_APPROVAL, "待审批", NotificationManager.IMPORTANCE_HIGH),
                    NotificationChannel(CHANNEL_TASK, "超期与待支持", NotificationManager.IMPORTANCE_HIGH),
                    NotificationChannel(CHANNEL_LEAD, "客户开发跟进", NotificationManager.IMPORTANCE_HIGH),
                    NotificationChannel(CHANNEL_RISK, "数据风险", NotificationManager.IMPORTANCE_DEFAULT),
                )
            )
        }
    }
}
