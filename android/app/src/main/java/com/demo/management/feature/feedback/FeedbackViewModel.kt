package com.demo.management.feature.feedback

import android.net.Uri
import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.BuildConfig
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.core.telemetry.TelemetryReporter
import com.demo.management.data.round5.FeedbackCreate
import com.demo.management.data.round5.FeedbackRow
import com.demo.management.data.round5.Round5Repository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class FeedbackUiState(
    val route: String? = null,
    val category: String = "bug",
    val description: String = "",
    val screenshot: Uri? = null,
    val screenshotConfirmed: Boolean = false,
    val items: List<FeedbackRow> = emptyList(),
    val loading: Boolean = false,
    val sending: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
)

@HiltViewModel
class FeedbackViewModel @Inject constructor(
    private val repository: Round5Repository,
    private val telemetry: TelemetryReporter,
) : ViewModel() {
    private val mutableState = MutableStateFlow(FeedbackUiState())
    val state: StateFlow<FeedbackUiState> = mutableState.asStateFlow()

    fun initialize(route: String?) {
        if (mutableState.value.route != null) return
        mutableState.value = mutableState.value.copy(route = route?.substringBefore('?')?.substringBefore('#'))
        refresh()
    }

    fun updateCategory(value: String) {
        mutableState.value = mutableState.value.copy(category = value, error = null, notice = null)
    }

    fun updateDescription(value: String) {
        mutableState.value = mutableState.value.copy(description = value.take(2000), error = null, notice = null)
    }

    fun selectScreenshot(uri: Uri?) {
        mutableState.value = mutableState.value.copy(screenshot = uri, screenshotConfirmed = false, error = null)
    }

    fun confirmScreenshot(value: Boolean) {
        mutableState.value = mutableState.value.copy(screenshotConfirmed = value)
    }

    fun refresh() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { repository.myFeedback() }
                .onSuccess { page -> mutableState.value = mutableState.value.copy(items = page.items, loading = false) }
                .onFailure(::showError)
        }
    }

    fun submit() {
        val state = mutableState.value
        if (state.description.trim().length < 5) {
            mutableState.value = state.copy(error = "请至少填写 5 个字的问题描述")
            return
        }
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(sending = true, error = null, notice = null)
            runCatching {
                repository.createFeedback(
                    FeedbackCreate(
                        category = state.category,
                        description = state.description.trim(),
                        currentRoute = state.route,
                        requestId = telemetry.lastRequestId(),
                        appVersion = BuildConfig.VERSION_NAME,
                        androidVersion = Build.VERSION.RELEASE,
                        deviceModel = Build.MODEL,
                    ),
                    state.screenshot.takeIf { state.screenshotConfirmed },
                )
            }.onSuccess { feedback ->
                telemetry.recordFeatureUsage("feedback_submitted")
                mutableState.value = mutableState.value.copy(
                    description = "",
                    screenshot = null,
                    screenshotConfirmed = false,
                    items = listOf(feedback) + mutableState.value.items.filterNot { it.id == feedback.id },
                    sending = false,
                    notice = "反馈已提交，可在下方查看处理进度",
                )
            }.onFailure(::showError)
        }
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(
            loading = false,
            sending = false,
            error = ApiErrorMapper.fromThrowable(error),
        )
    }
}
