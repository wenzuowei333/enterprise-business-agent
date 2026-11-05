package com.demo.management.feature.customer

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.CrmRepository
import com.demo.management.data.CustomerPanorama
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class CustomerPanoramaUiState(
    val customerCode: String? = null,
    val loading: Boolean = false,
    val panorama: CustomerPanorama? = null,
    val offline: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class CustomerPanoramaViewModel @Inject constructor(
    private val repository: CrmRepository,
) : ViewModel() {
    private val mutableState = MutableStateFlow(CustomerPanoramaUiState())
    val state: StateFlow<CustomerPanoramaUiState> = mutableState.asStateFlow()

    fun load(customerCode: String) {
        if (mutableState.value.customerCode == customerCode && mutableState.value.panorama != null) return
        viewModelScope.launch {
            mutableState.value = CustomerPanoramaUiState(customerCode = customerCode, loading = true)
            runCatching { repository.panorama(customerCode) }
                .onSuccess {
                    mutableState.value = CustomerPanoramaUiState(
                        customerCode = customerCode,
                        panorama = it,
                        offline = repository.lastReadWasOffline,
                    )
                }
                .onFailure {
                    mutableState.value = CustomerPanoramaUiState(
                        customerCode = customerCode,
                        error = ApiErrorMapper.fromThrowable(it),
                    )
                }
        }
    }
}
