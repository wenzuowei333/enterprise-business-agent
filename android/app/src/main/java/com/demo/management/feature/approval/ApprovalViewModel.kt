package com.demo.management.feature.approval

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import android.net.Uri
import com.demo.management.core.upload.AttachmentUploadManager
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.ApprovalDetailEnvelope
import com.demo.management.data.ApprovalSummary
import com.demo.management.data.CrmActionRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ApprovalUiState(
    val scope: String = "pending",
    val mode: String = "to_handle",
    val items: List<ApprovalSummary> = emptyList(),
    val total: Int = 0,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val processing: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
    val selected: ApprovalDetailEnvelope? = null,
    val comment: String = "",
)

@HiltViewModel
class ApprovalViewModel @Inject constructor(
    private val repository: CrmActionRepository,
    private val uploadManager: AttachmentUploadManager,
) : ViewModel() {
    private val mutableState = MutableStateFlow(ApprovalUiState())
    val state: StateFlow<ApprovalUiState> = mutableState.asStateFlow()

    init { refresh() }

    fun setScope(scope: String, mode: String = mutableState.value.mode) {
        mutableState.value = mutableState.value.copy(scope = scope, mode = mode, selected = null)
        refresh()
    }

    fun refresh() {
        load(reset = true)
    }

    fun loadMore() {
        val state = mutableState.value
        if (!state.loading && !state.loadingMore && state.items.size < state.total) load(reset = false)
    }

    private fun load(reset: Boolean) {
        viewModelScope.launch {
            val current = mutableState.value
            mutableState.value = current.copy(loading = reset, loadingMore = !reset, error = null)
            val offset = if (reset) 0 else current.items.size
            runCatching { repository.approvals(current.scope, current.mode, offset) }
                .onSuccess { page ->
                    mutableState.value = mutableState.value.copy(
                        items = if (reset) page.items else current.items + page.items,
                        total = page.total,
                        loading = false,
                        loadingMore = false,
                    )
                }
                .onFailure(::showError)
        }
    }

    fun open(id: Long) {
        viewModelScope.launch {
            runCatching { repository.approval(id) }
                .onSuccess { mutableState.value = mutableState.value.copy(selected = it, comment = "", error = null) }
                .onFailure(::showError)
        }
    }

    fun close() { mutableState.value = mutableState.value.copy(selected = null, comment = "") }

    fun updateComment(value: String) { mutableState.value = mutableState.value.copy(comment = value) }

    fun act(action: String) {
        val approval = mutableState.value.selected?.approval ?: return
        if (mutableState.value.processing) return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(processing = true, error = null)
            runCatching { repository.approvalAction(approval.id, action, mutableState.value.comment.takeIf { it.isNotBlank() }) }
                .onSuccess {
                    mutableState.value = mutableState.value.copy(processing = false, selected = null, notice = actionNotice(action))
                    refresh()
                }.onFailure(::showError)
        }
    }

    fun upload(uri: Uri) {
        val approval = mutableState.value.selected?.approval ?: return
        viewModelScope.launch {
            runCatching { uploadManager.enqueue(approval.id, uri) }
                .onSuccess { mutableState.value = mutableState.value.copy(notice = "附件已加入上传队列") }
                .onFailure(::showError)
        }
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(loading = false, loadingMore = false, processing = false, error = ApiErrorMapper.fromThrowable(error))
    }
}

private fun actionNotice(action: String) = when (action) {
    "approve" -> "审批已通过"
    "reject" -> "审批已驳回"
    else -> "已要求申请人补充"
}
