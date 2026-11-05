package com.demo.management.core.telemetry

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.demo.management.core.auth.TokenProvider
import com.demo.management.core.auth.SecureSessionStore
import com.demo.management.core.auth.hydrateTokenProvider
import com.demo.management.data.round3.ToolsRepository
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import java.util.concurrent.TimeUnit

@HiltWorker
class TelemetrySyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val reporter: TelemetryReporter,
    private val repository: ToolsRepository,
    private val tokenProvider: TokenProvider,
    private val sessionStore: SecureSessionStore,
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        if (tokenProvider.refreshToken().isNullOrBlank() && !hydrateTokenProvider(sessionStore.accessToken(), sessionStore.refreshToken(), tokenProvider)) return Result.success()
        val events = reporter.pending()
        if (events.isEmpty()) return Result.success()
        return runCatching {
            repository.telemetry(reporter.installationId(), events)
            reporter.acknowledge(events)
            Result.success()
        }.getOrElse { Result.retry() }
    }

    companion object {
        fun schedule(context: Context) {
            val constraints = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
            val request = PeriodicWorkRequestBuilder<TelemetrySyncWorker>(6, TimeUnit.HOURS).setConstraints(constraints).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("mobile-telemetry-sync", ExistingPeriodicWorkPolicy.UPDATE, request)
        }
    }
}
