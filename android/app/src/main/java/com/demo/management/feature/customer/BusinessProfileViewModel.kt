package com.demo.management.feature.customer

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.BusinessProfileUpdateRequest
import com.demo.management.data.CrmActionRepository
import com.demo.management.data.RecommendedProductPayload
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.LocalDate
import javax.inject.Inject

data class BusinessProfileForm(
    val customerType: String = "",
    val businessStatus: String = "",
    val statusNote: String = "",
    val updateNote: String = "",
    val recommendedProductName: String = "",
    val recommendedSpec: String = "",
    val recommendedQuote: String = "",
    val recommendReason: String = "",
    val customerFeedback: String = "",
    val nextAction: String = "",
)

data class BusinessProfileUiState(
    val customerCode: String = "",
    val customerName: String = "",
    val form: BusinessProfileForm = BusinessProfileForm(),
    val saving: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
)

@HiltViewModel
class BusinessProfileViewModel @Inject constructor(
    private val actions: CrmActionRepository,
) : ViewModel() {
    private val mutableState = MutableStateFlow(BusinessProfileUiState())
    val state: StateFlow<BusinessProfileUiState> = mutableState.asStateFlow()

    fun initialize(code: String, name: String) {
        if (mutableState.value.customerCode.isNotBlank()) return
        mutableState.value = mutableState.value.copy(customerCode = code, customerName = name)
    }

    fun update(transform: (BusinessProfileForm) -> BusinessProfileForm) {
        mutableState.value = mutableState.value.copy(form = transform(mutableState.value.form), error = null, notice = null)
    }

    fun submit() {
        val state = mutableState.value
        val form = state.form
        if (form.businessStatus.isBlank() && form.updateNote.isBlank() && form.recommendedProductName.isBlank()) {
            mutableState.value = state.copy(error = "请填写经营状态、更新说明或推荐产品")
            return
        }
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(saving = true, error = null)
            val recommended = if (form.recommendedProductName.isBlank()) emptyList() else listOf(
                RecommendedProductPayload(
                    productName = form.recommendedProductName,
                    spec = form.recommendedSpec.blankToNull(),
                    recommendedQuote = form.recommendedQuote.blankToNull(),
                    recommendReason = form.recommendReason.blankToNull(),
                    customerFeedback = form.customerFeedback.blankToNull(),
                    nextAction = form.nextAction.blankToNull(),
                )
            )
            runCatching {
                actions.saveBusinessProfile(
                    state.customerCode,
                    BusinessProfileUpdateRequest(
                        businessCustomerType = form.customerType.blankToNull(),
                        confirmedAt = LocalDate.now().toString(),
                        updateSource = "现场拜访",
                        updateType = "客户变化",
                        businessStatusLabel = form.businessStatus.blankToNull(),
                        businessStatusNote = form.statusNote.blankToNull(),
                        latestUpdateNote = form.updateNote.blankToNull(),
                        recommendedProducts = recommended,
                    ),
                )
            }.onSuccess { result ->
                mutableState.value = mutableState.value.copy(
                    saving = false,
                    notice = "已保存并同步主数据，共更新 ${result.changedFields.size} 项",
                )
            }.onFailure(::showError)
        }
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(saving = false, error = ApiErrorMapper.fromThrowable(error))
    }
}

private fun String.blankToNull(): String? = trim().takeIf { it.isNotEmpty() }
