package com.demo.management.feature.lead

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.data.round6.LeadAssignmentRequest
import com.demo.management.data.round6.LeadConversionApprovalRequest
import com.demo.management.data.round6.LeadFollowup
import com.demo.management.data.round6.LeadProductIntent
import com.demo.management.data.round6.LeadProjectPrefill
import com.demo.management.data.round6.LeadRow
import com.demo.management.data.round6.LeadUpdate
import com.demo.management.data.round6.Round6Repository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class LeadDetailUiState(
    val lead: LeadRow? = null,
    val loading: Boolean = true,
    val processing: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
    val projectPrefill: LeadProjectPrefill? = null,
)

@HiltViewModel
class LeadDetailViewModel @Inject constructor(
    private val repository: Round6Repository,
) : ViewModel() {
    private val mutableState = MutableStateFlow(LeadDetailUiState())
    val state: StateFlow<LeadDetailUiState> = mutableState.asStateFlow()

    fun load(leadId: Long) {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { repository.lead(leadId) }
                .onSuccess { mutableState.value = mutableState.value.copy(lead = it, loading = false) }
                .onFailure(::showError)
        }
    }

    fun assign(userId: Long?, note: String) = mutate { id -> repository.assignLead(id, LeadAssignmentRequest(userId, note.ifBlank { null })) }

    fun addFollowup(content: String, nextAt: String) {
        val lead = mutableState.value.lead ?: return
        if (content.isBlank()) return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(processing = true, error = null)
            runCatching { repository.submitFollowup(lead.id, LeadFollowup(content = content, nextFollowupAt = nextAt.ifBlank { null })) }
                .onSuccess { result ->
                    mutableState.value = mutableState.value.copy(
                        processing = false,
                        notice = if (result.queued) "跟进已离线保存，网络恢复后会同步。" else "跟进已提交。",
                    )
                    load(lead.id)
                }.onFailure(::showError)
        }
    }

    fun replaceProductIntent(name: String, note: String, productIntentsEnabled: Boolean) {
        if (!productIntentsEnabled) return
        mutate { id ->
            repository.updateLead(id, LeadUpdate(productIntents = listOf(LeadProductIntent(productName = name, note = note.ifBlank { null }))))
        }
    }

    fun requestConversion(note: String) {
        val lead = mutableState.value.lead ?: return
        if (!canRequestLeadConversion(lead.status, lead.currentApprovalStatus)) return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(processing = true, error = null)
            runCatching { repository.createConversionApproval(lead.id, LeadConversionApprovalRequest(submit = true, note = note.ifBlank { null })) }
                .onSuccess {
                    mutableState.value = mutableState.value.copy(processing = false, notice = "转客户申请已在线提交，审批通过后才会创建客户。")
                    load(lead.id)
                }.onFailure(::showError)
        }
    }

    fun loadProjectPrefill() {
        val lead = mutableState.value.lead ?: return
        if (lead.convertedCustomerCode.isNullOrBlank()) return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(processing = true, error = null)
            runCatching { repository.projectPrefill(lead.id) }
                .onSuccess { prefill -> mutableState.value = mutableState.value.copy(processing = false, projectPrefill = prefill) }
                .onFailure(::showError)
        }
    }

    private fun mutate(action: suspend (Long) -> LeadRow) {
        val lead = mutableState.value.lead ?: return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(processing = true, error = null)
            runCatching { action(lead.id) }
                .onSuccess { updated -> mutableState.value = mutableState.value.copy(lead = updated, processing = false, notice = "线索已更新。") }
                .onFailure(::showError)
        }
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(loading = false, processing = false, error = repository.errorMessage(error))
    }
}
