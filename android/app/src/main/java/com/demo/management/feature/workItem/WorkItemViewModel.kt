package com.demo.management.feature.workItem

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.CrmActionRepository
import com.demo.management.data.WorkItemRow
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class WorkItemUiState(
    val items: List<WorkItemRow> = emptyList(),
    val total: Int = 0,
    val loading: Boolean = false,
    val processing: Boolean = false,
    val error: String? = null,
    val selected: WorkItemRow? = null,
    val note: String = "",
)

@HiltViewModel
class WorkItemViewModel @Inject constructor(private val repository: CrmActionRepository) : ViewModel() {
    private val mutableState = MutableStateFlow(WorkItemUiState())
    val state: StateFlow<WorkItemUiState> = mutableState.asStateFlow()

    init { refresh() }

    fun refresh() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { repository.workItems() }
                .onSuccess { page -> mutableState.value = mutableState.value.copy(items = page.items, total = page.total, loading = false) }
                .onFailure(::showError)
        }
    }

    fun open(item: WorkItemRow) { mutableState.value = mutableState.value.copy(selected = item, note = "") }
    fun close() { mutableState.value = mutableState.value.copy(selected = null, note = "") }
    fun updateNote(value: String) { mutableState.value = mutableState.value.copy(note = value) }

    fun resolve(close: Boolean) {
        val item = mutableState.value.selected ?: return
        if (mutableState.value.processing) return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(processing = true, error = null)
            runCatching { repository.resolveWorkItem(item.id, mutableState.value.note.takeIf { it.isNotBlank() }, close) }
                .onSuccess {
                    mutableState.value = mutableState.value.copy(processing = false, selected = null)
                    refresh()
                }.onFailure(::showError)
        }
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(loading = false, processing = false, error = ApiErrorMapper.fromThrowable(error))
    }
}
