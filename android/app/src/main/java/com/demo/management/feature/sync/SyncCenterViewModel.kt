package com.demo.management.feature.sync

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.LocalSyncSummary
import com.demo.management.data.MobileDevice
import com.demo.management.data.SyncRepository
import com.demo.management.data.local.OutboxOperationEntity
import com.demo.management.data.local.SyncConflictEntity
import com.demo.management.core.notification.NotificationPreferenceStore
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SyncCenterUiState(
    val loading: Boolean = false,
    val summary: LocalSyncSummary? = null,
    val operations: List<OutboxOperationEntity> = emptyList(),
    val conflicts: List<SyncConflictEntity> = emptyList(),
    val devices: List<MobileDevice> = emptyList(),
    val error: String? = null,
    val notice: String? = null,
)

@HiltViewModel
class SyncCenterViewModel @Inject constructor(
    private val repository: SyncRepository,
    private val notificationPreferences: NotificationPreferenceStore,
) : ViewModel() {
    private val mutableState = MutableStateFlow(SyncCenterUiState())
    val state: StateFlow<SyncCenterUiState> = mutableState.asStateFlow()

    init { refresh() }

    fun refresh() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { loadState() }
                .onSuccess { mutableState.value = it.copy(loading = false) }
                .onFailure(::showError)
        }
    }

    fun syncNow() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null, notice = null)
            runCatching {
                repository.syncPending()
                repository.pull()
                loadState().copy(notice = "同步完成")
            }.onSuccess { mutableState.value = it.copy(loading = false) }
                .onFailure(::showError)
        }
    }

    fun cancel(operationId: String) {
        viewModelScope.launch {
            runCatching { repository.cancel(operationId); loadState().copy(notice = "已取消待提交操作") }
                .onSuccess { mutableState.value = it }
                .onFailure(::showError)
        }
    }

    fun keepServer(operationId: String) {
        viewModelScope.launch {
            runCatching { repository.keepServer(operationId); loadState().copy(notice = "已保留服务端资料") }
                .onSuccess { mutableState.value = it }
                .onFailure(::showError)
        }
    }

    fun retryLocal(operationId: String) {
        viewModelScope.launch {
            runCatching { repository.retryWithServerBase(operationId); loadState().copy(notice = "已重新加入待提交队列") }
                .onSuccess { mutableState.value = it }
                .onFailure(::showError)
        }
    }

    fun revokeDevice(sessionId: Long) {
        viewModelScope.launch {
            runCatching { repository.revokeDevice(sessionId); loadState().copy(notice = "设备会话已注销") }
                .onSuccess { mutableState.value = it }
                .onFailure(::showError)
        }
    }

    fun updateNotifications(sessionId: Long, approval: Boolean, task: Boolean, risk: Boolean) {
        viewModelScope.launch {
            runCatching {
                val device = repository.updateNotificationPreferences(sessionId, approval, task, risk)
                if (device.isCurrent) notificationPreferences.update(approval, task, risk)
                loadState().copy(notice = "通知偏好已保存")
            }.onSuccess { mutableState.value = it }
                .onFailure(::showError)
        }
    }

    private suspend fun loadState(): SyncCenterUiState {
        val devices = runCatching { repository.devices().items }.getOrDefault(emptyList())
        devices.firstOrNull { it.isCurrent }?.notificationPreferences?.let { current ->
            notificationPreferences.update(
                current["approval"] != false,
                current["task"] != false,
                current["risk"] != false,
            )
        }
        return SyncCenterUiState(
            summary = repository.summary(),
            operations = repository.recentOperations(),
            conflicts = repository.openConflicts(),
            devices = devices,
        )
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(loading = false, error = ApiErrorMapper.fromThrowable(error))
    }
}
