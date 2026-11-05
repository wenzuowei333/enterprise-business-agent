package com.demo.management.feature.task

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.CrmRepository
import com.demo.management.data.CrmTaskDetail
import com.demo.management.data.CrmTaskRow
import com.demo.management.data.ExecutionPayload
import com.demo.management.data.ExecutionProject
import com.demo.management.data.TaskFilter
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.OffsetDateTime
import javax.inject.Inject

data class TaskUiState(
    val view: String = "projects",
    val query: String = "",
    val projectFilter: String = "active",
    val taskFilter: String = "open",
    val payload: ExecutionPayload = ExecutionPayload(),
    val loading: Boolean = false,
    val error: String? = null,
    val selected: CrmTaskDetail? = null,
    val offline: Boolean = false,
)

@HiltViewModel
class TaskViewModel @Inject constructor(private val repository: CrmRepository) : ViewModel() {
    private val mutableState = MutableStateFlow(TaskUiState())
    val state: StateFlow<TaskUiState> = mutableState.asStateFlow()

    init { refresh() }

    fun setView(value: String) { mutableState.value = mutableState.value.copy(view = value, query = "") }
    fun updateQuery(value: String) { mutableState.value = mutableState.value.copy(query = value) }
    fun setProjectFilter(value: String) { mutableState.value = mutableState.value.copy(projectFilter = value) }
    fun setTaskFilter(value: String) { mutableState.value = mutableState.value.copy(taskFilter = value) }

    fun refresh() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { repository.execution() }
                .onSuccess {
                    mutableState.value = mutableState.value.copy(
                        payload = it,
                        loading = false,
                        offline = repository.lastReadWasOffline,
                    )
                }
                .onFailure(::showError)
        }
    }

    fun open(taskId: Long) {
        viewModelScope.launch {
            runCatching { repository.task(taskId) }
                .onSuccess { mutableState.value = mutableState.value.copy(selected = it, error = null, offline = repository.lastReadWasOffline) }
                .onFailure(::showError)
        }
    }

    fun closeDetail() { mutableState.value = mutableState.value.copy(selected = null) }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(loading = false, error = ApiErrorMapper.fromThrowable(error))
    }
}

internal fun filterExecutionProjects(items: List<ExecutionProject>, query: String, filter: String): List<ExecutionProject> {
    val keyword = query.trim().lowercase()
    return items.filter { project ->
        (keyword.isBlank() || listOf(project.projectName, project.projectCode, project.projectType, project.purpose)
            .any { it.orEmpty().lowercase().contains(keyword) }) && when (filter) {
            "overdue" -> project.overdue
            "closed" -> project.status in setOf("closed", "cancelled")
            "all" -> true
            else -> project.status !in setOf("closed", "cancelled")
        }
    }
}

internal fun filterExecutionTasks(items: List<CrmTaskRow>, query: String, filter: String): List<CrmTaskRow> {
    val keyword = query.trim().lowercase()
    return items.filter { task ->
        (keyword.isBlank() || listOf(task.customerName, task.customerCode, task.taskCode, task.businessIssuePoint, task.latestOwnerNextAction)
            .any { it.orEmpty().lowercase().contains(keyword) }) && when (filter) {
            "support" -> !task.isClosed && task.needSupport
            "blocked" -> !task.isClosed && task.isBlocked
            "overdue" -> !task.isClosed && isTaskOverdue(task)
            "closed" -> task.isClosed
            "all" -> true
            else -> !task.isClosed
        }
    }
}

internal fun isTaskOverdue(task: CrmTaskRow, now: Instant = Instant.now()): Boolean {
    val dueAt = task.feedbackDueAt?.let { value ->
        runCatching { OffsetDateTime.parse(value).toInstant() }
            .recoverCatching { Instant.parse(value) }
            .getOrNull()
    }
    return dueAt?.isBefore(now) == true
}

internal fun String.toFilter(): TaskFilter = when (this) {
    "not_started" -> TaskFilter(status = "not_started", closed = false)
    "in_progress" -> TaskFilter(status = "in_progress", closed = false)
    "support" -> TaskFilter(needSupport = true, closed = false)
    "blocked" -> TaskFilter(blocked = true, closed = false)
    "overdue" -> TaskFilter(overdue = true, closed = false)
    "closed" -> TaskFilter(closed = true)
    else -> TaskFilter(closed = false)
}
