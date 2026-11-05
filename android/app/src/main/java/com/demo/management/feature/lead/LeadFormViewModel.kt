package com.demo.management.feature.lead

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.data.round6.LeadCreate
import com.demo.management.data.round6.LeadDraftPolicy
import com.demo.management.data.round6.Round6Repository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class LeadFormSnapshot(
    val step: Int = 1,
    val leadName: String = "",
    val companyName: String = "",
    val contactName: String = "",
    val contactPhone: String = "",
    val source: String = "",
    val region: String = "",
    val businessLine: String = "",
    val intentSummary: String = "",
    val productName: String = "",
    val productNote: String = "",
    val nextFollowupAt: String = "",
)

data class LeadFormUiState(
    val form: LeadFormSnapshot = LeadFormSnapshot(),
    val loading: Boolean = true,
    val saving: Boolean = false,
    val submitting: Boolean = false,
    val duplicateMessage: String? = null,
    val error: String? = null,
    val notice: String? = null,
    val submittedLeadId: Long? = null,
)

@HiltViewModel
class LeadFormViewModel @Inject constructor(
    private val repository: Round6Repository,
) : ViewModel() {
    private val mutableState = MutableStateFlow(LeadFormUiState())
    val state: StateFlow<LeadFormUiState> = mutableState.asStateFlow()
    private var autosave: Job? = null
    private var features: LeadFormFeatures? = null

    fun configure(features: LeadFormFeatures) {
        if (this.features == features) return
        autosave?.cancel()
        this.features = features
        if (!features.offlineDraftsEnabled) {
            mutableState.value = mutableState.value.copy(loading = false, saving = false)
            return
        }
        viewModelScope.launch {
            val restored = runCatching { repository.loadNewLeadDraft(DRAFT_ID) }.getOrNull()
            mutableState.value = mutableState.value.copy(form = restored?.toSnapshot() ?: LeadFormSnapshot(), loading = false)
        }
    }

    fun update(transform: (LeadFormSnapshot) -> LeadFormSnapshot) {
        mutableState.value = mutableState.value.copy(form = transform(mutableState.value.form), error = null, notice = null, duplicateMessage = null)
        scheduleAutosave()
    }

    fun applyOcr(values: Map<String, String>, confirmedOverwrite: Boolean) {
        update { form ->
            val fields = applyOcrFieldsToLead(
                LeadOcrFields(form.companyName, form.contactName, form.contactPhone, form.region),
                values,
                confirmedOverwrite,
            )
            form.copy(
                companyName = fields.companyName,
                contactName = fields.contactName,
                contactPhone = fields.contactPhone,
                region = fields.region,
            )
        }
    }

    fun next() {
        validation(mutableState.value.form)?.let { message ->
            mutableState.value = mutableState.value.copy(error = message)
            return
        }
        update { it.copy(step = (it.step + 1).coerceAtMost(4)) }
    }

    fun previous() = update { it.copy(step = (it.step - 1).coerceAtLeast(1)) }

    fun submit() {
        val form = mutableState.value.form
        validateAll(form)?.let { message ->
            mutableState.value = mutableState.value.copy(error = message)
            return
        }
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(submitting = true, error = null, duplicateMessage = null)
            runCatching { repository.duplicateCheck(form.leadName, form.contactPhone) }
                .onSuccess { duplicates ->
                    val decision = leadDuplicateDecision(duplicates)
                    if (decision.blocksSubmission) {
                        mutableState.value = mutableState.value.copy(submitting = false, duplicateMessage = decision.message)
                    } else createOnline(form)
                }
                .onFailure { error ->
                    mutableState.value = mutableState.value.copy(submitting = false, error = repository.errorMessage(error))
                }
        }
    }

    private suspend fun createOnline(form: LeadFormSnapshot) {
        runCatching { repository.createLead(newLeadPayload(form, requireNotNull(features).productIntentsEnabled)) }
            .onSuccess { lead ->
                LeadDraftPolicy.clearAfterAutosave(autosave) { repository.clearNewLeadDraft(DRAFT_ID) }
                mutableState.value = mutableState.value.copy(
                    submitting = false,
                    submittedLeadId = lead.id,
                    notice = "线索已在线提交，可继续记录跟进。",
                )
            }
            .onFailure { error ->
                mutableState.value = mutableState.value.copy(submitting = false, error = repository.errorMessage(error))
            }
    }

    private fun scheduleAutosave() {
        val configuredFeatures = features ?: return
        if (!configuredFeatures.offlineDraftsEnabled) return
        autosave?.cancel()
        autosave = viewModelScope.launch {
            delay(450)
            val form = mutableState.value.form
            mutableState.value = mutableState.value.copy(saving = true)
            runCatching { repository.saveNewLeadDraft(DRAFT_ID, newLeadPayload(form, configuredFeatures.productIntentsEnabled)) }
            mutableState.value = mutableState.value.copy(saving = false)
        }
    }

    private fun validation(form: LeadFormSnapshot): String? = when (form.step) {
        1 -> if (form.leadName.isBlank()) "请填写线索名称" else null
        2 -> if (form.source.isBlank()) "请填写线索来源" else null
        else -> null
    }

    private fun validateAll(form: LeadFormSnapshot): String? = (1..2).firstNotNullOfOrNull { validation(form.copy(step = it)) }

    private fun LeadCreate.toSnapshot() = LeadFormSnapshot(
        leadName = leadName,
        companyName = companyName.orEmpty(),
        contactName = contactName.orEmpty(),
        contactPhone = contactPhone.orEmpty(),
        source = source.orEmpty(),
        region = region.orEmpty(),
        businessLine = businessLine.orEmpty(),
        intentSummary = intentSummary.orEmpty(),
        productName = productIntents.firstOrNull()?.productName.orEmpty(),
        productNote = productIntents.firstOrNull()?.note.orEmpty(),
        nextFollowupAt = nextFollowupAt.orEmpty(),
    )

    private companion object { const val DRAFT_ID = "new-lead" }
}
