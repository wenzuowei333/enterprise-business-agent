package com.demo.management.feature.projectApplication

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.ApprovalSummary
import com.demo.management.data.CrmProjectDraft
import com.demo.management.data.CrmProjectDraftRequest
import com.demo.management.data.CrmProjectTaskDraft
import com.demo.management.data.MobileCustomerOption
import com.demo.management.data.MobileUser
import com.demo.management.data.MobileUserOption
import com.demo.management.data.ProjectApplicationRepository
import com.squareup.moshi.Moshi
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.LocalDate
import javax.inject.Inject

data class SelectedProjectCustomer(
    val customerCode: String,
    val customerName: String,
    val executorUserId: Long? = null,
    val executorEmployeeCode: String? = null,
    val businessIssuePoint: String = "",
    val roundTarget: String = "",
    val feedbackDueAt: String = "",
)

data class ProjectApplicationSnapshot(
    val step: Int = 1,
    val projectName: String = "",
    val projectType: String = "客户项目",
    val businessLine: String = "",
    val purpose: String = "",
    val customerScopeNote: String = "",
    val startDate: String = LocalDate.now().toString(),
    val dueDate: String = "",
    val minimumAction: String = "完成一次有效客户跟进并提交反馈",
    val closureStandard: String = "客户任务已闭环，负责人确认下一步动作",
    val priority: String = "normal",
    val landingApproverUserId: Long? = null,
    val frontlineUserIds: List<Long> = emptyList(),
    val ownerUserId: Long? = null,
    val progressCcUserIds: List<Long> = emptyList(),
    val allowUnassignedTasks: Boolean = false,
    val customers: List<SelectedProjectCustomer> = emptyList(),
)

data class ProjectApplicationUiState(
    val applicant: MobileUser? = null,
    val form: ProjectApplicationSnapshot = ProjectApplicationSnapshot(),
    val users: List<MobileUserOption> = emptyList(),
    val customerOptions: List<MobileCustomerOption> = emptyList(),
    val customerQuery: String = "",
    val approvalId: Long? = null,
    val loading: Boolean = false,
    val saving: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
    val submitted: ApprovalSummary? = null,
)

@HiltViewModel
class ProjectApplicationViewModel @Inject constructor(
    private val repository: ProjectApplicationRepository,
    moshi: Moshi,
) : ViewModel() {
    private val adapter = moshi.adapter(ProjectApplicationSnapshot::class.java)
    private val mutableState = MutableStateFlow(ProjectApplicationUiState())
    val state: StateFlow<ProjectApplicationUiState> = mutableState.asStateFlow()
    private var autosaveJob: Job? = null
    private var initialized = false

    fun initialize(applicant: MobileUser, prefillCustomerCode: String? = null, prefillCustomerName: String? = null) {
        if (initialized) return
        initialized = true
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(applicant = applicant, loading = true)
            runCatching {
                val local = repository.loadLocal()
                val restored = local?.contentJson?.let(adapter::fromJson) ?: ProjectApplicationSnapshot(ownerUserId = applicant.id)
                val users = repository.users()
                val defaultApprover = restored.landingApproverUserId
                    ?: users.firstOrNull { it.username == "admin" || it.realName == "施总" }?.id
                val normalized = restored.copy(
                    landingApproverUserId = defaultApprover,
                    ownerUserId = restored.ownerUserId ?: applicant.id,
                    customers = if (prefillCustomerCode.isNullOrBlank() || restored.customers.any { it.customerCode == prefillCustomerCode }) {
                        restored.customers
                    } else {
                        restored.customers + SelectedProjectCustomer(
                            customerCode = prefillCustomerCode,
                            customerName = prefillCustomerName.orEmpty().ifBlank { prefillCustomerCode },
                        )
                    },
                )
                Triple(local?.approvalId, normalized, users)
            }.onSuccess { (approvalId, form, users) ->
                mutableState.value = mutableState.value.copy(
                    approvalId = approvalId,
                    form = form,
                    users = users,
                    loading = false,
                    notice = if (approvalId != null || form.projectName.isNotBlank()) "已恢复本地项目申请草稿" else null,
                )
                searchCustomers()
            }.onFailure(::showError)
        }
    }

    fun updateForm(transform: (ProjectApplicationSnapshot) -> ProjectApplicationSnapshot) {
        mutableState.value = mutableState.value.copy(form = transform(mutableState.value.form), error = null, notice = null)
        scheduleAutosave()
    }

    fun updateCustomerQuery(value: String) {
        mutableState.value = mutableState.value.copy(customerQuery = value)
    }

    fun searchCustomers() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { repository.customers(mutableState.value.customerQuery) }
                .onSuccess { page -> mutableState.value = mutableState.value.copy(customerOptions = page.items, loading = false) }
                .onFailure(::showError)
        }
    }

    fun toggleUser(userId: Long, cc: Boolean = false) {
        updateForm { form ->
            val source = if (cc) form.progressCcUserIds else form.frontlineUserIds
            val next = if (userId in source) source - userId else source + userId
            if (cc) form.copy(progressCcUserIds = next) else {
                val customers = if (next.size == 1) {
                    val user = mutableState.value.users.firstOrNull { it.id == next.first() }
                    form.customers.map { it.copy(executorUserId = user?.id, executorEmployeeCode = user?.employeeCode) }
                } else {
                    form.customers.map { row -> if (row.executorUserId in next) row else row.copy(executorUserId = null, executorEmployeeCode = null) }
                }
                form.copy(frontlineUserIds = next, customers = customers)
            }
        }
    }

    fun toggleCustomer(customer: MobileCustomerOption) {
        updateForm { form ->
            val existing = form.customers.any { it.customerCode == customer.customerCode }
            if (existing) form.copy(customers = form.customers.filterNot { it.customerCode == customer.customerCode })
            else {
                val executor = form.frontlineUserIds.singleOrNull()
                val user = mutableState.value.users.firstOrNull { it.id == executor }
                form.copy(
                    customers = form.customers + SelectedProjectCustomer(
                        customerCode = customer.customerCode,
                        customerName = customer.customerName,
                        executorUserId = user?.id,
                        executorEmployeeCode = user?.employeeCode,
                    )
                )
            }
        }
    }

    fun assignExecutor(customerCode: String, userId: Long?) {
        updateForm { form ->
            val user = mutableState.value.users.firstOrNull { it.id == userId }
            form.copy(customers = form.customers.map { row ->
                if (row.customerCode == customerCode) row.copy(executorUserId = user?.id, executorEmployeeCode = user?.employeeCode) else row
            })
        }
    }

    fun updateCustomer(customerCode: String, transform: (SelectedProjectCustomer) -> SelectedProjectCustomer) {
        updateForm { form ->
            form.copy(customers = form.customers.map { if (it.customerCode == customerCode) transform(it) else it })
        }
    }

    fun next() {
        val error = validateStep(mutableState.value.form)
        if (error != null) {
            mutableState.value = mutableState.value.copy(error = error)
            return
        }
        updateForm { it.copy(step = (it.step + 1).coerceAtMost(5)) }
    }

    fun previous() = updateForm { it.copy(step = (it.step - 1).coerceAtLeast(1)) }

    fun saveDraft() = persist(submitNow = false)

    fun submit() = persist(submitNow = true)

    private fun persist(submitNow: Boolean) {
        val form = mutableState.value.form
        val validation = validateAll(form)
        if (validation != null) {
            mutableState.value = mutableState.value.copy(error = validation)
            return
        }
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(saving = true, error = null, notice = null)
            runCatching {
                val payload = form.toRequest(submit = submitNow && mutableState.value.approvalId == null)
                val existingId = mutableState.value.approvalId
                if (existingId == null) repository.create(payload)
                else {
                    val updated = repository.update(existingId, payload.copy(submit = false))
                    if (submitNow) repository.submit(updated.id) else updated
                }
            }.onSuccess { approval ->
                if (submitNow || approval.status !in setOf("draft", "need_supplement")) {
                    repository.clearLocal()
                    mutableState.value = mutableState.value.copy(
                        approvalId = approval.id,
                        saving = false,
                        submitted = approval,
                        notice = "提交成功，当前处理人：${approval.currentHandlerUserLabel ?: "待分配"}",
                    )
                } else {
                    val json = adapter.toJson(form)
                    repository.saveLocal(json, approval.id)
                    mutableState.value = mutableState.value.copy(
                        approvalId = approval.id,
                        saving = false,
                        notice = "草稿已保存：${approval.approvalNo}",
                    )
                }
            }.onFailure(::showError)
        }
    }

    private fun scheduleAutosave() {
        autosaveJob?.cancel()
        autosaveJob = viewModelScope.launch {
            delay(400)
            val state = mutableState.value
            repository.saveLocal(adapter.toJson(state.form), state.approvalId)
        }
    }

    private fun validateStep(form: ProjectApplicationSnapshot): String? = when (form.step) {
        1 -> if (form.projectName.isBlank()) "请填写项目名称" else null
        2 -> when {
            form.landingApproverUserId == null -> "请选择项目落地审批人"
            form.ownerUserId == null -> "请选择细节审批人"
            form.frontlineUserIds.isEmpty() && !form.allowUnassignedTasks -> "请选择至少一名一线业务员"
            else -> null
        }
        3 -> if (form.customers.isEmpty()) "请至少选择一个客户" else null
        4 -> if (!form.allowUnassignedTasks && form.customers.any { it.executorUserId == null }) "仍有客户未分配执行人" else null
        else -> null
    }

    private fun validateAll(form: ProjectApplicationSnapshot): String? {
        for (step in 1..4) validateStep(form.copy(step = step))?.let { return it }
        return null
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(loading = false, saving = false, error = ApiErrorMapper.fromThrowable(error))
    }
}

private fun String.nullIfBlank(): String? = trim().takeIf { it.isNotEmpty() }

internal fun ProjectApplicationSnapshot.toRequest(submit: Boolean): CrmProjectDraftRequest = CrmProjectDraftRequest(
    title = "客户项目立项：${projectName.trim()}",
    description = purpose.nullIfBlank(),
    priority = priority,
    submit = submit,
    project = CrmProjectDraft(
        projectName = projectName.trim(),
        projectType = projectType.nullIfBlank(),
        purpose = purpose.nullIfBlank(),
        customerScopeNote = customerScopeNote.nullIfBlank(),
        businessLine = businessLine.nullIfBlank(),
        landingApproverUserId = landingApproverUserId,
        ownerUserId = ownerUserId,
        participantUserIds = frontlineUserIds,
        progressCcUserIds = progressCcUserIds,
        allowUnassignedTasks = allowUnassignedTasks,
        startDate = startDate.nullIfBlank(),
        dueDate = dueDate.nullIfBlank(),
        minimumAction = minimumAction.nullIfBlank(),
        closureStandard = closureStandard.nullIfBlank(),
        approvalStatus = if (submit) "submitted" else "draft",
    ),
    tasks = customers.map { row ->
        CrmProjectTaskDraft(
            customerCode = row.customerCode,
            executorUserId = row.executorUserId,
            executorEmployeeCode = row.executorEmployeeCode,
            businessIssuePoint = row.businessIssuePoint.nullIfBlank(),
            roundTarget = row.roundTarget.nullIfBlank(),
            feedbackDueAt = row.feedbackDueAt.nullIfBlank(),
        )
    },
)
