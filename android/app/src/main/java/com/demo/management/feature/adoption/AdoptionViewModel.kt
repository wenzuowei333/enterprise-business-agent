package com.demo.management.feature.adoption

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.round5.AdoptionOverview
import com.demo.management.data.round5.Round5Repository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class AdoptionUiState(
    val days: Int = 7,
    val overview: AdoptionOverview? = null,
    val loading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class AdoptionViewModel @Inject constructor(private val repository: Round5Repository) : ViewModel() {
    private val mutableState = MutableStateFlow(AdoptionUiState())
    val state: StateFlow<AdoptionUiState> = mutableState.asStateFlow()

    init { refresh() }

    fun setDays(days: Int) {
        mutableState.value = mutableState.value.copy(days = days)
        refresh()
    }

    fun refresh() {
        val days = mutableState.value.days
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { repository.adoptionOverview(days) }
                .onSuccess { mutableState.value = mutableState.value.copy(overview = it, loading = false) }
                .onFailure { mutableState.value = mutableState.value.copy(loading = false, error = ApiErrorMapper.fromThrowable(it)) }
        }
    }
}
