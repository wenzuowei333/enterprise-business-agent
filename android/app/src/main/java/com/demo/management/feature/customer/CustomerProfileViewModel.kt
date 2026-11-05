package com.demo.management.feature.customer

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.CrmActionRepository
import com.demo.management.data.CrmRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject
import com.demo.management.core.telemetry.TelemetryReporter

data class CustomerProfileForm(
    val customerName: String = "",
    val customerShortName: String = "",
    val customerType: String = "",
    val region: String = "",
    val contactName: String = "",
    val contactPhone: String = "",
    val contactChannel: String = "",
    val customerGroupName: String = "",
    val address: String = "",
)

data class CustomerProfileUiState(
    val customerCode: String = "",
    val original: CustomerProfileForm? = null,
    val originalUpdatedAt: String? = null,
    val form: CustomerProfileForm = CustomerProfileForm(),
    val loading: Boolean = false,
    val saving: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
)

@HiltViewModel
class CustomerProfileViewModel @Inject constructor(
    private val crm: CrmRepository,
    private val actions: CrmActionRepository,
    private val telemetry: TelemetryReporter,
) : ViewModel() {
    private val mutableState = MutableStateFlow(CustomerProfileUiState())
    val state: StateFlow<CustomerProfileUiState> = mutableState.asStateFlow()

    fun initialize(code: String) {
        if (mutableState.value.customerCode == code) return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(customerCode = code, loading = true)
            runCatching { crm.customer(code).customer }
                .onSuccess { customer ->
                    val form = customer.toProfileForm()
                    mutableState.value = mutableState.value.copy(
                        original = form,
                        originalUpdatedAt = customer.customerUpdatedAt,
                        form = form,
                        loading = false,
                    )
                }
                .onFailure(::showError)
        }
    }

    fun update(transform: (CustomerProfileForm) -> CustomerProfileForm) {
        mutableState.value = mutableState.value.copy(form = transform(mutableState.value.form), error = null, notice = null)
    }

    fun applyOcr(values: Map<String, String>) {
        if (values.isEmpty()) return
        update { form -> applyOcrProfileValues(form, values) }
        telemetry.recordFeatureUsage("contact_ocr")
        mutableState.value = mutableState.value.copy(notice = "名片字段已回填，请确认后再保存")
    }

    fun save() {
        val state = mutableState.value
        val original = state.original ?: return
        val changes = customerProfileChanges(state.form, original)
        if (changes.isEmpty()) {
            mutableState.value = state.copy(error = "请至少修改一项客户资料")
            return
        }
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(saving = true, error = null)
            runCatching {
                actions.saveCustomerProfile(
                    customerCode = state.customerCode,
                    changes = changes,
                    baseValues = customerProfileValues(original),
                    baseUpdatedAt = state.originalUpdatedAt,
                )
            }.onSuccess { submission ->
                    val result = submission.value
                    mutableState.value = mutableState.value.copy(
                        original = mutableState.value.form,
                        saving = false,
                        notice = if (submission.queued) {
                            "网络不可用，资料更新已加入待提交队列"
                        } else {
                            "已保存并同步主数据，共更新 ${result?.changedFields?.size ?: 0} 个字段"
                        },
                    )
                }.onFailure(::showError)
        }
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(loading = false, saving = false, error = ApiErrorMapper.fromThrowable(error))
    }
}

internal fun applyOcrProfileValues(form: CustomerProfileForm, values: Map<String, String>): CustomerProfileForm = form.copy(
    customerName = values["customer_name"] ?: form.customerName,
    contactName = values["contact_name"] ?: form.contactName,
    contactPhone = values["contact_phone"] ?: form.contactPhone,
    contactChannel = values["contact_channel"] ?: form.contactChannel,
    address = values["address"] ?: form.address,
)

private fun com.demo.management.data.LinkedCustomerRow.toProfileForm() = CustomerProfileForm(
    customerName = customerName,
    customerShortName = customerShortName.orEmpty(),
    customerType = customerType.orEmpty(),
    region = region.orEmpty(),
    contactName = contactName.orEmpty(),
    contactPhone = contactPhone.orEmpty(),
    contactChannel = contactChannel.orEmpty(),
    customerGroupName = customerGroupName.orEmpty(),
    address = address.orEmpty(),
)

internal fun customerProfileChanges(current: CustomerProfileForm, before: CustomerProfileForm): Map<String, String?> {
    val fields = listOf(
        "customer_name" to (before.customerName to current.customerName),
        "customer_short_name" to (before.customerShortName to current.customerShortName),
        "customer_type" to (before.customerType to current.customerType),
        "region" to (before.region to current.region),
        "contact_name" to (before.contactName to current.contactName),
        "contact_phone" to (before.contactPhone to current.contactPhone),
        "contact_channel" to (before.contactChannel to current.contactChannel),
        "customer_group_name" to (before.customerGroupName to current.customerGroupName),
        "address" to (before.address to current.address),
    )
    return fields.mapNotNull { (key, values) ->
        val (old, new) = values
        if (old == new) null else key to new.trim().takeIf { it.isNotEmpty() }
    }.toMap()
}

internal fun customerProfileValues(form: CustomerProfileForm): Map<String, String?> = mapOf(
    "customer_name" to form.customerName,
    "customer_short_name" to form.customerShortName,
    "customer_type" to form.customerType,
    "region" to form.region,
    "contact_name" to form.contactName,
    "contact_phone" to form.contactPhone,
    "contact_channel" to form.contactChannel,
    "customer_group_name" to form.customerGroupName,
    "address" to form.address,
)
