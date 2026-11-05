package com.demo.management.feature.assistant

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.core.telemetry.TelemetryReporter
import com.demo.management.data.round5.AssistantDraftRequest
import com.demo.management.data.round5.AssistantDraftResponse
import com.demo.management.data.round5.Round5Repository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

enum class AiDraftType(val label: String) {
    FOLLOWUP("跟进内容整理"),
    APPROVAL("审批意见草稿"),
    PROJECT("项目进展摘要"),
}

data class AiDraftUiState(
    val type: AiDraftType = AiDraftType.FOLLOWUP,
    val text: String = "",
    val resourceId: String = "",
    val result: AssistantDraftResponse? = null,
    val loading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class AiDraftViewModel @Inject constructor(
    private val repository: Round5Repository,
    private val telemetry: TelemetryReporter,
) : ViewModel() {
    private val mutableState = MutableStateFlow(AiDraftUiState())
    val state: StateFlow<AiDraftUiState> = mutableState.asStateFlow()

    fun selectType(value: AiDraftType) {
        mutableState.value = mutableState.value.copy(type = value, resourceId = "", result = null, error = null)
    }

    fun updateText(value: String) {
        mutableState.value = mutableState.value.copy(text = value.take(8000), error = null)
    }

    fun updateResourceId(value: String) {
        mutableState.value = mutableState.value.copy(resourceId = value.filter(Char::isDigit).take(12), error = null)
    }

    fun generate() {
        val current = mutableState.value
        val id = current.resourceId.toLongOrNull()
        if (current.text.isBlank() && id == null) {
            mutableState.value = current.copy(error = "请填写原始内容或业务编号")
            return
        }
        val request = AssistantDraftRequest(
            text = current.text.trim().takeIf(String::isNotEmpty),
            taskId = id.takeIf { current.type == AiDraftType.FOLLOWUP },
            approvalId = id.takeIf { current.type == AiDraftType.APPROVAL },
            projectId = id.takeIf { current.type == AiDraftType.PROJECT },
        )
        viewModelScope.launch {
            telemetry.recordFeatureUsage("ai_draft_requested")
            mutableState.value = current.copy(loading = true, error = null, result = null)
            runCatching {
                when (current.type) {
                    AiDraftType.FOLLOWUP -> repository.followupDraft(request)
                    AiDraftType.APPROVAL -> repository.approvalOpinionDraft(request)
                    AiDraftType.PROJECT -> repository.projectSummaryDraft(request)
                }
            }.onSuccess { result ->
                telemetry.recordFeatureUsage("ai_draft_${current.type.name.lowercase()}")
                telemetry.recordFeatureUsage("ai_draft_structured_success")
                mutableState.value = mutableState.value.copy(loading = false, result = result)
            }.onFailure { error ->
                telemetry.recordFeatureUsage("ai_draft_failed")
                mutableState.value = mutableState.value.copy(loading = false, error = ApiErrorMapper.fromThrowable(error))
            }
        }
    }

    fun markAdopted() {
        telemetry.recordFeatureUsage("ai_draft_adopted")
    }
}
