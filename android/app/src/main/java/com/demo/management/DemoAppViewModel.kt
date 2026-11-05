package com.demo.management

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.AppRepository
import com.demo.management.data.BootstrapPayload
import com.demo.management.data.WorkbenchPayload
import com.demo.management.data.LocalSyncSummary
import com.demo.management.data.SyncRepository
import com.demo.management.data.local.FormDraftDao
import com.demo.management.data.local.ProjectDraftDao
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject
import com.demo.management.core.sync.NetworkFailurePolicy
import com.demo.management.core.auth.SecureSessionStore
import com.demo.management.core.onboarding.shouldShowOnboarding
import com.demo.management.core.appearance.AppearancePreferenceStore
import com.demo.designsystem.theme.AppearanceSettings
import com.demo.designsystem.theme.GlassPreference
import com.demo.designsystem.theme.LiquidThemeMode
import com.demo.designsystem.theme.MotionPreference

data class AppUiState(
    val sessionReady: Boolean = false,
    val authenticated: Boolean = false,
    val loading: Boolean = false,
    val error: String? = null,
    val bootstrap: BootstrapPayload? = null,
    val workbench: WorkbenchPayload? = null,
    val localDraftCount: Int = 0,
    val syncSummary: LocalSyncSummary? = null,
    val onboardingRequired: Boolean = false,
    val appearanceSettings: AppearanceSettings = AppearanceSettings.Default,
)

@HiltViewModel
class DemoAppViewModel @Inject constructor(
    private val repository: AppRepository,
    private val formDraftDao: FormDraftDao,
    private val projectDraftDao: ProjectDraftDao,
    private val syncRepository: SyncRepository,
    private val sessionStore: SecureSessionStore,
    private val appearancePreferenceStore: AppearancePreferenceStore,
) : ViewModel() {
    private val mutableState = MutableStateFlow(AppUiState())
    val state: StateFlow<AppUiState> = mutableState.asStateFlow()

    init {
        viewModelScope.launch {
            appearancePreferenceStore.settings.collect { appearance ->
                mutableState.value = mutableState.value.copy(appearanceSettings = appearance)
            }
        }
        viewModelScope.launch {
            val restored = repository.restoreSession()
            mutableState.value = mutableState.value.copy(sessionReady = true, authenticated = restored)
            if (restored) loadBootstrapAndHome()
        }
    }

    fun login(username: String, password: String) {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { repository.login(username.trim(), password) }
                .onSuccess {
                    mutableState.value = mutableState.value.copy(authenticated = true, loading = false)
                    loadBootstrapAndHome()
                }
                .onFailure(::showError)
        }
    }

    fun logout() {
        viewModelScope.launch {
            repository.logout()
            mutableState.value = AppUiState(
                sessionReady = true,
                appearanceSettings = mutableState.value.appearanceSettings,
            )
        }
    }

    fun setThemeMode(value: LiquidThemeMode) {
        viewModelScope.launch { appearancePreferenceStore.setThemeMode(value) }
    }

    fun setGlassPreference(value: GlassPreference) {
        viewModelScope.launch { appearancePreferenceStore.setGlassPreference(value) }
    }

    fun setMotionPreference(value: MotionPreference) {
        viewModelScope.launch { appearancePreferenceStore.setMotionPreference(value) }
    }

    fun refreshHome() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { repository.workbench() }
                .onSuccess { payload -> mutableState.value = mutableState.value.copy(loading = false, workbench = payload) }
                .onFailure(::showError)
        }
    }

    fun syncNow() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching {
                syncRepository.syncPending()
                syncRepository.pull()
                syncRepository.summary()
            }.onSuccess { summary ->
                mutableState.value = mutableState.value.copy(loading = false, syncSummary = summary)
            }.onFailure(::showError)
        }
    }

    fun refreshSyncSummary() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(syncSummary = syncRepository.summary())
        }
    }

    fun refreshLocalDrafts() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(
                localDraftCount = formDraftDao.count() + projectDraftDao.count(),
            )
        }
    }

    fun clearLocalDrafts() {
        viewModelScope.launch {
            formDraftDao.deleteAll()
            projectDraftDao.deleteAll()
            mutableState.value = mutableState.value.copy(localDraftCount = 0)
        }
    }

    fun completeOnboarding() {
        val bootstrap = mutableState.value.bootstrap ?: return
        sessionStore.completeOnboarding(bootstrap.user.id, bootstrap.app.onboardingVersion)
        mutableState.value = mutableState.value.copy(onboardingRequired = false)
    }

    private suspend fun loadBootstrapAndHome() {
        mutableState.value = mutableState.value.copy(loading = true, error = null)
        runCatching { repository.bootstrap() to repository.workbench() }
            .onSuccess { (bootstrap, workbench) ->
                val onboardingRequired = shouldShowOnboarding(
                    enabled = bootstrap.app.featureFlags["onboarding"] == true,
                    completedVersion = sessionStore.completedOnboardingVersion(bootstrap.user.id),
                    configuredVersion = bootstrap.app.onboardingVersion,
                )
                mutableState.value = mutableState.value.copy(
                    sessionReady = true,
                    authenticated = true,
                    loading = false,
                    bootstrap = bootstrap,
                    workbench = workbench,
                    localDraftCount = formDraftDao.count() + projectDraftDao.count(),
                    syncSummary = syncRepository.summary(),
                    onboardingRequired = onboardingRequired,
                )
                repository.requestSync()
            }
            .onFailure { error ->
                if (error is retrofit2.HttpException && error.code() == 401) {
                    repository.logout()
                    mutableState.value = AppUiState(
                        sessionReady = true,
                        error = "登录已过期，请重新登录",
                        appearanceSettings = mutableState.value.appearanceSettings,
                    )
                } else if (NetworkFailurePolicy.isRetryable(error) && syncRepository.cacheIsReadable()) {
                    val cached = repository.cachedBootstrap()
                    if (cached != null) {
                        mutableState.value = mutableState.value.copy(
                            sessionReady = true,
                            authenticated = true,
                            loading = false,
                            bootstrap = cached,
                            workbench = null,
                            error = "当前网络不可用，已进入 24 小时离线工作模式",
                            localDraftCount = formDraftDao.count() + projectDraftDao.count(),
                            syncSummary = syncRepository.summary(),
                        )
                    } else showError(error)
                } else showError(error)
            }
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(loading = false, error = ApiErrorMapper.fromThrowable(error))
    }
}
