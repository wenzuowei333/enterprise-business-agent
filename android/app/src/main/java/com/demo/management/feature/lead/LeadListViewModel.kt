package com.demo.management.feature.lead

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.data.round6.LeadRow
import com.demo.management.data.round6.Round6Repository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class LeadListUiState(
    val query: String = "",
    val status: String? = null,
    val items: List<LeadRow> = emptyList(),
    val total: Int = 0,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val offline: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class LeadListViewModel @Inject constructor(
    private val repository: Round6Repository,
) : ViewModel() {
    private val mutableState = MutableStateFlow(LeadListUiState())
    val state: StateFlow<LeadListUiState> = mutableState.asStateFlow()
    private var generation = 0L
    private var nextRequestId = 0L
    private var activeRequestId = 0L

    init { refresh() }

    fun updateQuery(value: String) {
        generation += 1
        mutableState.value = mutableState.value.copy(query = value, loading = false, loadingMore = false)
    }

    fun setStatus(status: String?) {
        mutableState.value = mutableState.value.copy(status = status)
        refresh()
    }

    fun refresh() = load(reset = true)

    fun loadMore() = load(reset = false)

    private fun load(reset: Boolean) {
        val current = mutableState.value
        if (!reset && (current.loadingMore || current.items.size >= current.total)) return
        val request = LeadListRequest(
            generation = if (reset) ++generation else generation,
            requestId = ++nextRequestId,
            query = current.query,
            status = current.status,
            offset = if (reset) 0 else current.items.size,
        )
        activeRequestId = request.requestId
        viewModelScope.launch {
            mutableState.value = current.copy(
                loading = reset,
                loadingMore = !reset,
                error = if (reset) null else current.error,
            )
            runCatching {
                repository.leads(
                    query = request.query,
                    status = request.status,
                    offset = request.offset,
                )
            }.onSuccess { page ->
                if (!acceptsLeadListResponse(request, generation, activeRequestId)) return@onSuccess
                mutableState.value = mutableState.value.copy(
                    items = if (reset) page.items else current.items + page.items,
                    total = page.total,
                    loading = false,
                    loadingMore = false,
                    offline = repository.lastReadWasOffline,
                    error = null,
                )
            }.onFailure { error ->
                if (!acceptsLeadListResponse(request, generation, activeRequestId)) return@onFailure
                mutableState.value = mutableState.value.copy(
                    loading = false,
                    loadingMore = false,
                    error = repository.errorMessage(error),
                )
            }
        }
    }
}
