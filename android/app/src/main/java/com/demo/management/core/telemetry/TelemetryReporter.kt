package com.demo.management.core.telemetry

import android.content.Context
import android.os.Build
import com.demo.management.BuildConfig
import com.demo.management.data.round3.TelemetryEvent
import com.squareup.moshi.Moshi
import dagger.hilt.android.qualifiers.ApplicationContext
import java.time.Instant
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class TelemetryReporter @Inject constructor(
    @ApplicationContext context: Context,
    moshi: Moshi,
) {
    private val preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private val adapter = moshi.adapter(TelemetryEvent::class.java)
    @Volatile private var latestRequestId: String? = null

    @Synchronized
    fun recordApi(route: String, status: Int?, durationMs: Int, requestId: String? = null, networkError: String? = null) {
        if (!requestId.isNullOrBlank() && (networkError != null || (status ?: 0) >= 400)) latestRequestId = requestId.take(120)
        val type = if (networkError != null || (status ?: 0) >= 400) "api_error" else "api_timing"
        record(
            TelemetryEvent(
                eventType = type,
                occurredAt = Instant.now().toString(),
                requestId = requestId,
                route = sanitizedTelemetryRoute(route),
                code = networkError ?: status?.toString(),
                durationMs = durationMs.coerceIn(0, 600_000),
                appVersion = BuildConfig.VERSION_NAME,
                deviceModel = Build.MODEL.take(160),
                androidVersion = Build.VERSION.RELEASE.take(40),
            )
        )
    }

    fun lastRequestId(): String? = latestRequestId

    fun installationId(): String {
        val existing = preferences.getString(INSTALLATION_ID, null)
        if (!existing.isNullOrBlank()) return existing
        return UUID.randomUUID().toString().also { preferences.edit().putString(INSTALLATION_ID, it).apply() }
    }

    @Synchronized
    fun recordCrash(error: Throwable) {
        record(
            TelemetryEvent(
                eventType = "crash",
                occurredAt = Instant.now().toString(),
                code = error.javaClass.simpleName.take(120),
                appVersion = BuildConfig.VERSION_NAME,
                deviceModel = Build.MODEL.take(160),
                androidVersion = Build.VERSION.RELEASE.take(40),
            )
        )
    }

    @Synchronized
    fun recordFeatureUsage(feature: String) {
        record(
            TelemetryEvent(
                eventType = "feature_usage",
                occurredAt = Instant.now().toString(),
                code = feature.telemetryKey(),
                appVersion = BuildConfig.VERSION_NAME,
                deviceModel = Build.MODEL.take(160),
                androidVersion = Build.VERSION.RELEASE.take(40),
            )
        )
    }

    @Synchronized
    fun recordFormTiming(form: String, durationMs: Long) {
        record(
            TelemetryEvent(
                eventType = "form_timing",
                occurredAt = Instant.now().toString(),
                code = form.telemetryKey(),
                durationMs = durationMs.coerceIn(0L, 600_000L).toInt(),
                appVersion = BuildConfig.VERSION_NAME,
                deviceModel = Build.MODEL.take(160),
                androidVersion = Build.VERSION.RELEASE.take(40),
            )
        )
    }

    @Synchronized
    fun pending(limit: Int = 50): List<TelemetryEvent> = preferences.getStringSet(EVENTS, emptySet()).orEmpty()
        .mapNotNull { runCatching { adapter.fromJson(it) }.getOrNull() }
        .sortedBy { it.occurredAt }
        .take(limit)

    @Synchronized
    fun acknowledge(events: List<TelemetryEvent>) {
        if (events.isEmpty()) return
        val stored = preferences.getStringSet(EVENTS, emptySet()).orEmpty().toMutableSet()
        events.map(adapter::toJson).forEach(stored::remove)
        preferences.edit().putStringSet(EVENTS, stored).apply()
    }

    private fun record(event: TelemetryEvent) {
        val stored = preferences.getStringSet(EVENTS, emptySet()).orEmpty().toMutableList()
        stored += adapter.toJson(event)
        preferences.edit().putStringSet(EVENTS, stored.takeLast(MAX_EVENTS).toSet()).apply()
    }

    private companion object {
        const val PREFS = "mobile_telemetry"
        const val EVENTS = "events"
        const val INSTALLATION_ID = "installation_id"
        const val MAX_EVENTS = 100
    }
}

private fun String.telemetryKey(): String = lowercase()
    .filter { it.isLetterOrDigit() || it == '_' || it == '-' }
    .take(80)
