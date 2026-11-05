package com.demo.management.feature.data

import android.content.Context
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.round3.AssistantMessageResponse
import com.demo.management.data.round3.CheckRepository
import com.demo.management.data.round3.DashboardOverview
import com.demo.management.data.round3.DataModule
import com.demo.management.data.round3.DataRepository
import com.demo.management.data.round3.ImportBatch
import com.demo.management.data.round3.InventoryCheckBatch
import com.demo.management.data.round3.ToolsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.LocalDate
import javax.inject.Inject

data class DataHubUiState(
    val section: String = "query",
    val modules: List<DataModule> = emptyList(),
    val selectedModule: String? = null,
    val query: String = "",
    val dateFrom: String = "",
    val dateTo: String = "",
    val warehouse: String = "",
    val items: List<Map<String, Any?>> = emptyList(),
    val total: Int = 0,
    val summary: Map<String, Any?> = emptyMap(),
    val checkKind: String = "inventory",
    val checkDate: String = "",
    val checkQuery: String = "",
    val checkResultType: String = "",
    val inventoryBatches: List<InventoryCheckBatch> = emptyList(),
    val selectedInventoryBatch: InventoryCheckBatch? = null,
    val checkItems: List<Map<String, Any?>> = emptyList(),
    val checkTotal: Int = 0,
    val receivableBatch: ImportBatch? = null,
    val dashboardRange: String = "7d",
    val dashboard: DashboardOverview? = null,
    val assistantInput: String = "",
    val assistantMessages: List<String> = emptyList(),
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
)

@HiltViewModel
class DataHubViewModel @Inject constructor(
    private val dataRepository: DataRepository,
    private val checkRepository: CheckRepository,
    private val toolsRepository: ToolsRepository,
    @ApplicationContext private val context: Context,
) : ViewModel() {
    private val mutableState = MutableStateFlow(DataHubUiState())
    val state: StateFlow<DataHubUiState> = mutableState.asStateFlow()

    init { loadOverview() }

    fun setSection(section: String) {
        mutableState.value = mutableState.value.copy(section = section, error = null, notice = null)
        when (section) {
            "checks" -> refreshChecks()
            "dashboard" -> loadDashboard()
            "ai" -> loadAssistantHistory()
        }
    }

    fun selectModule(key: String) {
        mutableState.value = mutableState.value.copy(selectedModule = key, items = emptyList(), total = 0)
        refreshData()
    }

    fun updateQuery(value: String) { mutableState.value = mutableState.value.copy(query = value) }
    fun updateDateFrom(value: String) { mutableState.value = mutableState.value.copy(dateFrom = value) }
    fun updateDateTo(value: String) { mutableState.value = mutableState.value.copy(dateTo = value) }
    fun updateWarehouse(value: String) { mutableState.value = mutableState.value.copy(warehouse = value) }
    fun updateCheckDate(value: String) { mutableState.value = mutableState.value.copy(checkDate = value) }
    fun updateCheckQuery(value: String) { mutableState.value = mutableState.value.copy(checkQuery = value) }
    fun updateAssistantInput(value: String) { mutableState.value = mutableState.value.copy(assistantInput = value) }
    fun clearMessage() { mutableState.value = mutableState.value.copy(error = null, notice = null) }

    fun applyDatePreset(preset: String) {
        val range = dateRangeForPreset(preset) ?: return
        mutableState.value = mutableState.value.copy(dateFrom = range.from, dateTo = range.to)
        refreshData()
    }

    fun applyDeepLink(module: String?, query: String?) {
        if (module.isNullOrBlank() || query.isNullOrBlank()) return
        mutableState.value = mutableState.value.copy(section = "query", selectedModule = module, query = query, items = emptyList(), total = 0)
        refreshData()
    }

    fun refreshData() = loadData(reset = true)
    fun loadMoreData() {
        val current = mutableState.value
        if (!current.loadingMore && current.items.size < current.total) loadData(reset = false)
    }

    fun setCheckKind(kind: String) {
        mutableState.value = mutableState.value.copy(checkKind = kind, checkItems = emptyList(), checkTotal = 0, checkResultType = "", checkQuery = "")
        refreshChecks()
    }

    fun setCheckResultType(type: String) {
        mutableState.value = mutableState.value.copy(checkResultType = type)
        refreshChecks()
    }

    fun refreshCheckResults() = refreshChecks()

    fun loadMoreCheckResults() {
        val current = mutableState.value
        if (current.loadingMore || current.checkItems.size >= current.checkTotal) return
        if (current.checkKind == "inventory") {
            current.selectedInventoryBatch?.let { loadInventoryResults(it.id, reset = false) }
        } else {
            loadReceivableResults(reset = false)
        }
    }

    fun openInventoryBatch(batch: InventoryCheckBatch) {
        mutableState.value = mutableState.value.copy(selectedInventoryBatch = batch)
        loadInventoryResults(batch.id)
    }

    fun uploadInventory(uri: Uri) = runAction("库存核验已完成") {
        val batch = checkRepository.uploadInventory(context.contentResolver, uri, optionalCheckDate(mutableState.value.checkDate))
        mutableState.value = mutableState.value.copy(selectedInventoryBatch = batch, checkDate = batch.dataDate.orEmpty())
        refreshInventoryBatches()
        loadInventoryResults(batch.id)
    }

    fun uploadReceivable(uri: Uri) = runAction("应收查询表已上传，请预校验") {
        val batch = checkRepository.uploadReceivable(context.contentResolver, uri, optionalCheckDate(mutableState.value.checkDate))
        mutableState.value = mutableState.value.copy(receivableBatch = batch, checkDate = batch.dataDate.orEmpty())
    }

    fun validateReceivable() {
        val batch = mutableState.value.receivableBatch ?: return
        runAction("预校验完成，可确认提交") {
            mutableState.value = mutableState.value.copy(receivableBatch = checkRepository.validateReceivable(batch.id))
        }
    }

    fun commitReceivable() {
        val batch = mutableState.value.receivableBatch ?: return
        runAction("应收校验已提交") {
            mutableState.value = mutableState.value.copy(receivableBatch = checkRepository.commitReceivable(batch.id))
            loadReceivableResults()
        }
    }

    fun setDashboardRange(range: String) {
        mutableState.value = mutableState.value.copy(dashboardRange = range)
        loadDashboard()
    }

    fun sendAssistantMessage() {
        val message = mutableState.value.assistantInput.trim()
        if (message.isEmpty()) return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null, assistantInput = "")
            runCatching { toolsRepository.sendAssistant(message) }
                .onSuccess { response ->
                    mutableState.value = mutableState.value.copy(
                        loading = false,
                        assistantMessages = mutableState.value.assistantMessages + "我：$message" + assistantText(response),
                    )
                }
                .onFailure(::showError)
        }
    }

    private fun loadOverview() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { dataRepository.overview() }
                .onSuccess { overview ->
                    val first = overview.modules.firstOrNull { it.key !in setOf("inventory_check", "receivable_check") }?.key
                    mutableState.value = mutableState.value.copy(loading = false, modules = overview.modules, selectedModule = first)
                    if (first != null) refreshData()
                }
                .onFailure(::showError)
        }
    }

    private fun loadData(reset: Boolean) {
        val current = mutableState.value
        val module = current.selectedModule ?: return
        viewModelScope.launch {
            mutableState.value = current.copy(loading = reset, loadingMore = !reset, error = null)
            val offset = if (reset) 0 else current.items.size
            runCatching { dataRepository.page(module, current.query, current.dateFrom.ifBlank { null }, current.dateTo.ifBlank { null }, current.warehouse, offset) }
                .onSuccess { page -> mutableState.value = mutableState.value.copy(items = if (reset) page.items else current.items + page.items, total = page.total, summary = page.summary, loading = false, loadingMore = false) }
                .onFailure(::showError)
        }
    }

    private fun refreshChecks() {
        if (mutableState.value.checkKind == "inventory") refreshInventoryBatches() else loadReceivableResults()
    }

    private fun refreshInventoryBatches() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { checkRepository.inventoryBatches() }
                .onSuccess { page -> mutableState.value = mutableState.value.copy(loading = false, inventoryBatches = page.items) }
                .onFailure(::showError)
        }
    }

    private fun loadInventoryResults(batchId: Long, reset: Boolean = true) {
        val current = mutableState.value
        viewModelScope.launch {
            mutableState.value = current.copy(loading = reset, loadingMore = !reset, error = null)
            val offset = if (reset) 0 else current.checkItems.size
            runCatching { checkRepository.inventoryResults(batchId, current.checkResultType.ifBlank { null }, current.checkQuery.ifBlank { null }, offset) }
                .onSuccess { page -> mutableState.value = mutableState.value.copy(loading = false, loadingMore = false, checkItems = if (reset) page.items else current.checkItems + page.items, checkTotal = page.total, summary = page.summary) }
                .onFailure(::showError)
        }
    }

    private fun loadReceivableResults(reset: Boolean = true) {
        val current = mutableState.value
        viewModelScope.launch {
            mutableState.value = current.copy(loading = reset, loadingMore = !reset, error = null)
            val offset = if (reset) 0 else current.checkItems.size
            runCatching { checkRepository.receivableResults(current.checkResultType.ifBlank { null }, current.checkQuery.ifBlank { null }, offset) }
                .onSuccess { page -> mutableState.value = mutableState.value.copy(loading = false, loadingMore = false, checkItems = if (reset) page.items else current.checkItems + page.items, checkTotal = page.total, summary = page.summary) }
                .onFailure(::showError)
        }
    }

    private fun loadDashboard() {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null)
            runCatching { toolsRepository.dashboard(mutableState.value.dashboardRange) }
                .onSuccess { mutableState.value = mutableState.value.copy(loading = false, dashboard = it) }
                .onFailure(::showError)
        }
    }

    private fun loadAssistantHistory() {
        viewModelScope.launch {
            runCatching { toolsRepository.assistantMessages() }
                .onSuccess { rows -> mutableState.value = mutableState.value.copy(assistantMessages = rows.map { row -> row["assistant_message"]?.toString().orEmpty() }.filter { it.isNotBlank() }) }
                .onFailure(::showError)
        }
    }

    private fun runAction(success: String, action: suspend () -> Unit) {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(loading = true, error = null, notice = null)
            runCatching { action() }
                .onSuccess { mutableState.value = mutableState.value.copy(loading = false, notice = success) }
                .onFailure(::showError)
        }
    }

    private fun assistantText(response: AssistantMessageResponse): String =
        response.message["assistant_message"]?.toString()?.let { "\nAI：$it" } ?: "\nAI：已生成分析"

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(loading = false, loadingMore = false, error = ApiErrorMapper.fromThrowable(error))
    }
}
