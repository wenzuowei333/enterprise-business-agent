package com.demo.management.core.sync

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.demo.management.core.auth.SecureSessionStore
import com.demo.management.core.auth.TokenProvider
import com.demo.management.core.auth.hydrateTokenProvider
import com.demo.management.data.SyncRepository
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import java.util.concurrent.TimeUnit

@HiltWorker
class MobileSyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val repository: SyncRepository,
    private val tokenProvider: TokenProvider,
    private val sessionStore: SecureSessionStore,
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        if (tokenProvider.refreshToken().isNullOrBlank() &&
            !hydrateTokenProvider(sessionStore.accessToken(), sessionStore.refreshToken(), tokenProvider)
        ) return Result.success()
        return runCatching {
            repository.syncPending()
            repository.pull()
            Result.success()
        }.getOrElse { error ->
            repository.recordPullFailure(error.message ?: "同步失败")
            if (runAttemptCount >= 4) Result.failure() else Result.retry()
        }
    }

    companion object {
        private const val PERIODIC_NAME = "mobile-crm-sync"
        private const val IMMEDIATE_NAME = "mobile-crm-sync-now"

        private val constraints = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<MobileSyncWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                PERIODIC_NAME,
                ExistingPeriodicWorkPolicy.UPDATE,
                request,
            )
        }

        fun runNow(context: Context) {
            val request = OneTimeWorkRequestBuilder<MobileSyncWorker>().setConstraints(constraints).build()
            WorkManager.getInstance(context).enqueueUniqueWork(IMMEDIATE_NAME, ExistingWorkPolicy.REPLACE, request)
        }
    }
}
