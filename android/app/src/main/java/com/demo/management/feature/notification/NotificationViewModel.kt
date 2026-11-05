package com.demo.management.feature.notification

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.round3.MobileNotification
import com.demo.management.data.round3.ToolsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject
import com.demo.management.core.notification.NotificationPreferenceStore

data class NotificationUiState(val items: List<MobileNotification> = emptyList(), val loading: Boolean = false, val error: String? = null)

@HiltViewModel
class NotificationViewModel @Inject constructor(
    private val repository: ToolsRepository,
    private val preferences: NotificationPreferenceStore,
) : ViewModel() {
    private val mutableState = MutableStateFlow(NotificationUiState())
    val state: StateFlow<NotificationUiState> = mutableState.asStateFlow()
    init { refresh() }

    fun refresh() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { repository.notifications() }
                .onSuccess { mutableState.value = NotificationUiState(items = it.items) }
                .onFailure { mutableState.value = NotificationUiState(error = ApiErrorMapper.fromThrowable(it)) }
        }
    }

    fun handled(item: MobileNotification) {
        viewModelScope.launch {
            runCatching { repository.processNotification(item.notificationId) }
                .onSuccess { refresh() }
                .onFailure { mutableState.value = mutableState.value.copy(error = ApiErrorMapper.fromThrowable(it)) }
        }
    }

    fun snooze(item: MobileNotification) {
        preferences.snooze(item)
        mutableState.value = mutableState.value.copy(items = mutableState.value.items.filterNot { it.notificationId == item.notificationId })
    }
}
