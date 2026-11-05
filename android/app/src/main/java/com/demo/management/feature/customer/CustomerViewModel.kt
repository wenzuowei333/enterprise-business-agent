package com.demo.management.feature.customer

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.CrmRepository
import com.demo.management.data.LinkedCustomerRow
import com.demo.management.data.LinkedCustomerSummary
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class CustomerUiState(
    val query: String = "",
    val scope: String? = null,
    val items: List<LinkedCustomerRow> = emptyList(),
    val total: Int = 0,
    val summary: LinkedCustomerSummary = LinkedCustomerSummary(),
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val error: String? = null,
    val offline: Boolean = false,
)

@HiltViewModel
class CustomerViewModel @Inject constructor(private val repository: CrmRepository) : ViewModel() {
    private val mutableState = MutableStateFlow(CustomerUiState())
    val state: StateFlow<CustomerUiState> = mutableState.asStateFlow()

    init { refresh() }

    fun updateQuery(value: String) { mutableState.value = mutableState.value.copy(query = value) }

    fun setScope(value: String?) {
        mutableState.value = mutableState.value.copy(scope = value)
        refresh()
    }

    fun refresh() = load(reset = true)

    fun loadMore() {
        val state = mutableState.value
        if (!state.loading && !state.loadingMore && state.items.size < state.total) load(reset = false)
    }

    private fun load(reset: Boolean) {
        viewModelScope.launch {
            val current = mutableState.value
            mutableState.value = current.copy(loading = reset, loadingMore = !reset, error = null)
            val offset = if (reset) 0 else current.items.size
            runCatching { repository.customers(current.query, current.scope, offset) }
                .onSuccess { page ->
                    mutableState.value = mutableState.value.copy(
                        items = if (reset) page.items else current.items + page.items,
                        total = page.total,
                        summary = page.summary,
                        loading = false,
                        loadingMore = false,
                        offline = repository.lastReadWasOffline,
                    )
                }
                .onFailure(::showError)
        }
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(loading = false, loadingMore = false, error = ApiErrorMapper.fromThrowable(error))
    }
}
