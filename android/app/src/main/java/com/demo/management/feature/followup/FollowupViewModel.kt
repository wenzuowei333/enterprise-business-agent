package com.demo.management.feature.followup

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.ApprovalSummary
import com.demo.management.data.CrmActionRepository
import com.demo.management.data.CrmRepository
import com.demo.management.data.CrmTaskDetail
import com.demo.management.data.FollowupApprovalRequest
import com.demo.management.data.FollowupPayload
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
import android.net.Uri
import android.os.SystemClock
import com.demo.management.core.telemetry.TelemetryReporter

data class FollowupForm(
    val followupDate: String = LocalDate.now().toString(),
    val method: String = "电话",
    val frontlineAction: String = "",
    val customerFeedback: String = "",
    val currentNeed: String = "",
    val blockerReason: String = "",
    val blockerNote: String = "",
    val nextAction: String = "",
    val nextFollowupAt: String = "",
    val minimumActionDone: Boolean = false,
    val customerProfileUpdated: Boolean = false,
    val businessProfileUpdated: Boolean = false,
    val businessProfileApprovalId: Long? = null,
    val needSupport: Boolean = false,
    val needType: String = "业务协同",
    val isClosed: Boolean = false,
)

data class FollowupUiState(
    val task: CrmTaskDetail? = null,
    val form: FollowupForm = FollowupForm(),
    val loading: Boolean = false,
    val saving: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
    val approval: ApprovalSummary? = null,
    val attachments: List<Uri> = emptyList(),
)

@HiltViewModel
class FollowupViewModel @Inject constructor(
    private val crm: CrmRepository,
    private val actions: CrmActionRepository,
    private val telemetry: TelemetryReporter,
    moshi: Moshi,
) : ViewModel() {
    private val adapter = moshi.adapter(FollowupForm::class.java)
    private val mutableState = MutableStateFlow(FollowupUiState())
    val state: StateFlow<FollowupUiState> = mutableState.asStateFlow()
    private var taskId: Long = 0
    private var autosave: Job? = null
    private var formStartedAt: Long = 0L

    fun initialize(id: Long) {
        if (taskId == id) return
        taskId = id
        formStartedAt = SystemClock.elapsedRealtime()
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true)
            runCatching {
                val detail = crm.task(id)
                val local = actions.loadDraft("followup", id.toString())?.let(adapter::fromJson)
                detail to (local ?: FollowupForm())
            }.onSuccess { (detail, form) ->
                mutableState.value = mutableState.value.copy(task = detail, form = form, loading = false)
            }.onFailure(::showError)
        }
    }

    fun update(transform: (FollowupForm) -> FollowupForm) {
        mutableState.value = mutableState.value.copy(form = transform(mutableState.value.form), error = null, notice = null)
        autosave?.cancel()
        autosave = viewModelScope.launch {
            delay(400)
            actions.saveDraft("followup", taskId.toString(), adapter.toJson(mutableState.value.form))
        }
    }

    fun addAttachments(values: List<Uri>) {
        mutableState.value = mutableState.value.copy(attachments = (mutableState.value.attachments + values).distinct().take(10))
    }

    fun recordVoiceInput() {
        telemetry.recordFeatureUsage("voice_input")
    }

    fun submit() {
        val detail = mutableState.value.task ?: return
        val form = mutableState.value.form
        val validation = when {
            form.customerFeedback.isBlank() -> "请填写客户反馈"
            form.nextAction.isBlank() -> "请填写下一步动作"
            form.needSupport && form.currentNeed.isBlank() && form.blockerNote.isBlank() -> "需要支持时请填写当前需求或卡点说明"
            else -> null
        }
        if (validation != null) {
            mutableState.value = mutableState.value.copy(error = validation)
            return
        }
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(saving = true, error = null)
            runCatching {
                actions.submitFollowup(
                    FollowupApprovalRequest(
                        title = "跟进事实审核：${detail.task.customerName}",
                        followup = FollowupPayload(
                            projectId = detail.project.id,
                            taskId = detail.task.id,
                            followupDate = form.followupDate,
                            method = form.method.blankToNull(),
                            frontlineAction = form.frontlineAction.blankToNull(),
                            customerFeedback = form.customerFeedback.blankToNull(),
                            currentNeed = form.currentNeed.blankToNull(),
                            needType = if (form.needSupport) form.needType else null,
                            blockerReason = form.blockerReason.blankToNull(),
                            blockerNote = form.blockerNote.blankToNull(),
                            nextAction = form.nextAction.blankToNull(),
                            nextFollowupAt = form.nextFollowupAt.blankToNull(),
                            minimumActionDone = form.minimumActionDone,
                            customerProfileUpdated = form.customerProfileUpdated,
                            businessProfileUpdated = form.businessProfileUpdated,
                            businessProfileApprovalId = form.businessProfileApprovalId,
                            needSupport = form.needSupport,
                            isClosed = form.isClosed,
                        ),
                    ),
                    mutableState.value.attachments,
                )
            }.onSuccess { submission ->
                if (formStartedAt > 0L) telemetry.recordFormTiming("followup", SystemClock.elapsedRealtime() - formStartedAt)
                actions.clearDraft("followup", taskId.toString())
                mutableState.value = mutableState.value.copy(
                    saving = false,
                    approval = submission.value,
                    attachments = emptyList(),
                    notice = when {
                        submission.queued -> "网络不可用，已加入待提交队列"
                        submission.attachmentsPending -> "审批已提交，附件将在网络稳定后继续上传"
                        else -> "已提交细节审批人审核"
                    },
                )
            }.onFailure(::showError)
        }
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(loading = false, saving = false, error = ApiErrorMapper.fromThrowable(error))
    }
}

private fun String.blankToNull(): String? = trim().takeIf { it.isNotEmpty() }
