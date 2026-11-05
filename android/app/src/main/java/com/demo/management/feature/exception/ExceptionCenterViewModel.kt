package com.demo.management.feature.exception

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.ExceptionRepository
import com.demo.management.data.MobileAiActionExecution
import com.demo.management.data.MobileAiActionProposal
import com.demo.management.data.MobileAiActionValidation
import com.demo.management.data.MobileDiagnosisJob
import com.demo.management.data.MobileExceptionCase
import com.demo.management.data.MobileExceptionCapabilities
import com.demo.management.data.MobileExceptionDetail
import com.demo.management.data.MobileExceptionSummary
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.UUID

data class ExceptionCenterUiState(
    val view: String = "cases",
    val query: String = "",
    val domain: String? = null,
    val severity: String? = null,
    val status: String? = null,
    val assignment: String? = null,
    val items: List<MobileExceptionCase> = emptyList(),
    val total: Int = 0,
    val summary: MobileExceptionSummary = MobileExceptionSummary(),
    val capabilities: MobileExceptionCapabilities = MobileExceptionCapabilities(),
    val selected: MobileExceptionDetail? = null,
    val diagnosisJob: MobileDiagnosisJob? = null,
    val actions: List<MobileAiActionProposal> = emptyList(),
    val actionTotal: Int = 0,
    val selectedAction: MobileAiActionProposal? = null,
    val actionValidation: MobileAiActionValidation? = null,
    val actionExecution: MobileAiActionExecution? = null,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val loadingDetail: Boolean = false,
    val loadingActions: Boolean = false,
    val processingAction: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class ExceptionCenterViewModel @Inject constructor(
    private val repository: ExceptionRepository,
) : ViewModel() {
    private val mutableState = MutableStateFlow(ExceptionCenterUiState())
    val state: StateFlow<ExceptionCenterUiState> = mutableState.asStateFlow()
    private var diagnosisPolling: Job? = null

    init { refresh() }

    fun updateQuery(value: String) { mutableState.value = mutableState.value.copy(query = value) }
    fun setView(value: String) {
        mutableState.value = mutableState.value.copy(view = value)
        if (value == "actions" && mutableState.value.actions.isEmpty()) loadActions()
    }
    fun setDomain(value: String?) { mutableState.value = mutableState.value.copy(domain = value); refresh() }
    fun setSeverity(value: String?) { mutableState.value = mutableState.value.copy(severity = value); refresh() }
    fun setStatus(value: String?) { mutableState.value = mutableState.value.copy(status = value); refresh() }
    fun setAssignment(value: String?) { mutableState.value = mutableState.value.copy(assignment = value); refresh() }
    fun refresh() = load(reset = true)

    fun loadMore() {
        val current = mutableState.value
        if (!current.loading && !current.loadingMore && current.items.size < current.total) load(reset = false)
    }

    fun open(caseNo: String) {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loadingDetail = true, error = null)
            runCatching { repository.detail(caseNo) }
                .onSuccess { mutableState.value = mutableState.value.copy(selected = it, loadingDetail = false) }
                .onFailure(::showError)
        }
    }

    fun closeDetail() { mutableState.value = mutableState.value.copy(selected = null) }

    fun diagnose(caseNo: String) {
        diagnosisPolling?.cancel()
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loadingDetail = true, error = null)
            runCatching { repository.requestDiagnosis(caseNo) }
                .onSuccess { job ->
                    mutableState.value = mutableState.value.copy(diagnosisJob = job, loadingDetail = false)
                    pollDiagnosis(job)
                }
                .onFailure(::showError)
        }
    }

    fun loadActions() {
        val current = mutableState.value
        if (current.loadingActions) return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loadingActions = true, error = null)
            runCatching { repository.actions() }
                .onSuccess { page ->
                    mutableState.value = mutableState.value.copy(
                        actions = page.items,
                        actionTotal = page.total,
                        loadingActions = false,
                    )
                }
                .onFailure(::showError)
        }
    }

    fun openAction(proposal: MobileAiActionProposal) {
        mutableState.value = mutableState.value.copy(
            selectedAction = proposal,
            actionValidation = null,
            actionExecution = null,
        )
    }

    fun closeAction() {
        mutableState.value = mutableState.value.copy(
            selectedAction = null,
            actionValidation = null,
            actionExecution = null,
        )
    }

    fun validateAction() {
        val proposal = mutableState.value.selectedAction ?: return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(processingAction = true, error = null)
            runCatching { repository.validateAction(proposal.proposalNo) }
                .onSuccess { validation ->
                    mutableState.value = mutableState.value.copy(
                        selectedAction = validation.proposal,
                        actionValidation = validation,
                        actionExecution = null,
                        processingAction = false,
                    )
                }
                .onFailure(::showError)
        }
    }

    fun executeValidatedAction() {
        val validation = mutableState.value.actionValidation ?: return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(processingAction = true, error = null)
            runCatching { repository.executeAction(validation, "android:${UUID.randomUUID()}") }
                .onSuccess { execution ->
                    mutableState.value = mutableState.value.copy(
                        actionExecution = execution,
                        actionValidation = null,
                        processingAction = false,
                    )
                    loadActions()
                    refresh()
                }
                .onFailure(::showError)
        }
    }

    private fun load(reset: Boolean) {
        viewModelScope.launch {
            val current = mutableState.value
            mutableState.value = current.copy(loading = reset, loadingMore = !reset, error = null)
            runCatching {
                repository.cases(
                    query = current.query,
                    domain = current.domain,
                    severity = current.severity,
                    status = current.status,
                    assignment = current.assignment,
                    offset = if (reset) 0 else current.items.size,
                )
            }.onSuccess { page ->
                mutableState.value = mutableState.value.copy(
                    items = if (reset) page.items else current.items + page.items,
                    total = page.total,
                    summary = page.summary,
                    capabilities = page.capabilities,
                    loading = false,
                    loadingMore = false,
                )
                if (page.capabilities.executeAction && mutableState.value.actions.isEmpty()) loadActions()
            }.onFailure(::showError)
        }
    }

    private fun pollDiagnosis(initial: MobileDiagnosisJob) {
        if (initial.status in TERMINAL_JOB_STATUSES) {
            finishDiagnosis(initial)
            return
        }
        diagnosisPolling = viewModelScope.launch {
            repeat(90) {
                delay(2_000)
                val next = runCatching { repository.diagnosisJob(initial.id) }
                    .getOrElse { error -> showError(error); return@launch }
                mutableState.value = mutableState.value.copy(diagnosisJob = next)
                if (next.status in TERMINAL_JOB_STATUSES) {
                    finishDiagnosis(next)
                    return@launch
                }
            }
            mutableState.value = mutableState.value.copy(error = "诊断仍在后台处理中，可稍后刷新查看结果")
        }
    }

    private fun finishDiagnosis(job: MobileDiagnosisJob) {
        mutableState.value = mutableState.value.copy(diagnosisJob = job)
        if (job.status == "completed") {
            open(job.caseNo)
            refresh()
        } else if (job.status == "failed") {
            mutableState.value = mutableState.value.copy(error = job.errorMessage ?: "诊断失败，请稍后重试")
        }
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(
            loading = false,
            loadingMore = false,
            loadingDetail = false,
            loadingActions = false,
            processingAction = false,
            error = ApiErrorMapper.fromThrowable(error),
        )
    }

    private companion object {
        val TERMINAL_JOB_STATUSES = setOf("completed", "failed", "cancelled")
    }
}
