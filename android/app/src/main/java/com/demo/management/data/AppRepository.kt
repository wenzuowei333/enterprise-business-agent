package com.demo.management.data

import android.os.Build
import android.content.Context
import com.demo.management.BuildConfig
import com.demo.management.core.auth.SecureSessionStore
import com.demo.management.core.auth.TokenProvider
import com.demo.management.core.sync.MobileSyncWorker
import com.demo.management.data.local.AppDatabase
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton
import com.squareup.moshi.Moshi

@Singleton
class AppRepository @Inject constructor(
    private val authApi: AuthApi,
    private val mobileApi: MobileApi,
    private val sessionStore: SecureSessionStore,
    private val tokenProvider: TokenProvider,
    private val syncRepository: SyncRepository,
    private val database: AppDatabase,
    moshi: Moshi,
    @ApplicationContext private val context: Context,
) {
    private val bootstrapAdapter = moshi.adapter(BootstrapPayload::class.java)
    fun restoreSession(): Boolean {
        val accessToken = sessionStore.accessToken()
        val refreshToken = sessionStore.refreshToken()
        if (refreshToken.isNullOrBlank()) return false
        tokenProvider.update(accessToken.orEmpty(), refreshToken)
        return true
    }

    suspend fun login(username: String, password: String): MobileTokenResponse {
        val response = authApi.login(
            MobileLoginRequest(
                username = username,
                password = password,
                deviceId = sessionStore.deviceId(),
                deviceName = "${Build.MANUFACTURER} ${Build.MODEL}".trim(),
                appVersion = BuildConfig.VERSION_NAME,
                androidVersion = Build.VERSION.RELEASE,
                deviceModel = Build.MODEL,
            )
        )
        sessionStore.save(response.accessToken, response.refreshToken)
        tokenProvider.update(response.accessToken, response.refreshToken)
        return response
    }

    suspend fun logout() {
        val refreshToken = tokenProvider.refreshToken() ?: sessionStore.refreshToken()
        if (!refreshToken.isNullOrBlank()) {
            runCatching { authApi.logout(MobileRefreshRequest(refreshToken, sessionStore.deviceId())) }
        }
        sessionStore.clearTokens()
        tokenProvider.clear()
        withContext(Dispatchers.IO) {
            syncRepository.clearLocalData()
            database.clearAllTables()
        }
        sessionStore.markDatabaseKeyRotation()
    }

    suspend fun bootstrap(): BootstrapPayload = mobileApi.bootstrap().also {
        sessionStore.saveBootstrap(bootstrapAdapter.toJson(it))
        syncRepository.applyBootstrapFeatureFlags(it.app.featureFlags)
    }

    fun cachedBootstrap(): BootstrapPayload? = sessionStore.bootstrap()?.let {
        runCatching { bootstrapAdapter.fromJson(it) }.getOrNull()
    }

    suspend fun home(): HomePayload = mobileApi.home()

    suspend fun workbench(): WorkbenchPayload = mobileApi.workbench()

    fun requestSync() = MobileSyncWorker.runNow(context)
}
