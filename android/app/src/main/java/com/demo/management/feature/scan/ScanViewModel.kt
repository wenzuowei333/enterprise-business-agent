package com.demo.management.feature.scan

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.round3.ScanResult
import com.demo.management.data.round3.ToolsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ScanUiState(
    val input: String = "",
    val loading: Boolean = false,
    val result: ScanResult? = null,
    val error: String? = null,
)

@HiltViewModel
class ScanViewModel @Inject constructor(private val repository: ToolsRepository) : ViewModel() {
    private val mutableState = MutableStateFlow(ScanUiState())
    val state: StateFlow<ScanUiState> = mutableState.asStateFlow()

    fun updateInput(value: String) { mutableState.value = mutableState.value.copy(input = value) }
    fun resolve(value: String = mutableState.value.input) {
        val query = value.trim()
        if (query.isEmpty() || mutableState.value.loading) return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(input = query, loading = true, error = null)
            runCatching { repository.scan(query) }
                .onSuccess { mutableState.value = mutableState.value.copy(loading = false, result = it) }
                .onFailure { mutableState.value = mutableState.value.copy(loading = false, error = ApiErrorMapper.fromThrowable(it)) }
        }
    }
}
