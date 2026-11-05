package com.demo.management.feature.lead

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import com.demo.designsystem.components.LiquidDialog as AlertDialog
import com.demo.designsystem.components.LiquidActionButton as Button
import com.demo.designsystem.components.ContentSection as Card
import androidx.compose.material3.CircularProgressIndicator
import com.demo.designsystem.components.LiquidFilterChip as FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.management.data.round6.LeadPublicPoolRow
import com.demo.management.data.round6.LeadSlaException
import com.demo.management.data.round6.Round6Repository
import com.demo.designsystem.components.LiquidSearchBar
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@Composable
fun LeadWorkbenchScreen(
    permissions: Collection<String>,
    featureFlags: Map<String, Boolean>,
    canCreate: Boolean,
    onCreate: () -> Unit,
    onOpen: (Long) -> Unit,
    poolViewModel: LeadPublicPoolViewModel = hiltViewModel(),
    slaViewModel: LeadSlaExceptionsViewModel = hiltViewModel(),
) {
    val sections = LeadOperationsSection.entries.filter { canViewLeadOperationsSection(it, permissions, featureFlags) }
    var activeSection by remember(sections) { mutableStateOf(sections.firstOrNull() ?: LeadOperationsSection.Mine) }

    Column(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            items(sections, key = { it.name }) { section ->
                FilterChip(
                    selected = activeSection == section,
                    onClick = { activeSection = section },
                    label = { Text(section.label) },
                )
            }
        }
        Box(modifier = Modifier.weight(1f)) {
            when (activeSection) {
                LeadOperationsSection.Mine -> LeadListScreen(canCreate = canCreate, onCreate = onCreate, onOpen = onOpen)
                LeadOperationsSection.Today -> LeadSlaExceptionsPanel(stateValue = null, todayOnly = true, onOpen = onOpen, viewModel = slaViewModel)
                LeadOperationsSection.DueSoon -> LeadSlaExceptionsPanel(stateValue = "due_soon", onOpen = onOpen, viewModel = slaViewModel)
                LeadOperationsSection.Overdue -> LeadSlaExceptionsPanel(stateValue = "overdue", onOpen = onOpen, viewModel = slaViewModel)
                LeadOperationsSection.ClaimablePool -> LeadPublicPoolPanel(onClaimed = onOpen, viewModel = poolViewModel)
            }
        }
    }
}

@Composable
private fun LeadPublicPoolPanel(
    onClaimed: (Long) -> Unit,
    viewModel: LeadPublicPoolViewModel,
) {
    val state by viewModel.state.collectAsState()
    var claimTarget by remember { mutableStateOf<LeadPublicPoolRow?>(null) }
    LaunchedEffect(Unit) { viewModel.refresh() }
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            LiquidSearchBar(
                value = state.query,
                onValueChange = viewModel::updateQuery,
                modifier = Modifier.fillMaxWidth(),
                placeholder = "搜索线索或公司",
                onSearch = viewModel::refresh,
            )
        }
        item { Text("公海线索仅在线展示，认领后才可查看完整联系人资料。", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        state.error?.let { error -> item { Text(error, color = MaterialTheme.colorScheme.error) } }
        if (state.loading) item { CircularProgressIndicator() }
        if (!state.loading && state.items.isEmpty()) item { Text("当前没有可认领线索") }
        items(state.items, key = { it.id }) { lead ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(lead.leadName, fontWeight = FontWeight.Bold)
                        Text(leadSlaStateLabel(lead.sla.state), color = MaterialTheme.colorScheme.primary)
                    }
                    Text(lead.leadNo, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(listOfNotNull(lead.companyName, lead.source, lead.region, lead.businessLine).joinToString(" · ").ifBlank { "来源与区域待补充" })
                    Text("优先级：${lead.priority} · 截止：${lead.sla.deadline ?: "待计算"}", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Button(onClick = { claimTarget = lead }, enabled = !state.claiming) { Text("认领线索") }
                }
            }
        }
        if (state.items.size < state.total) item {
            TextButton(onClick = viewModel::loadMore, modifier = Modifier.fillMaxWidth()) {
                if (state.loadingMore) CircularProgressIndicator() else Text("加载更多")
            }
        }
    }
    claimTarget?.let { lead ->
        AlertDialog(
            onDismissRequest = { if (!state.claiming) claimTarget = null },
            title = { Text("确认认领线索") },
            text = { Text("认领后该线索将进入您的私有工作台，并开始计算跟进时限。") },
            confirmButton = {
                TextButton(
                    enabled = !state.claiming,
                    onClick = { viewModel.claim(lead.id) { claimedId -> claimTarget = null; onClaimed(claimedId) } },
                ) { Text("确认认领") }
            },
            dismissButton = { TextButton(onClick = { claimTarget = null }, enabled = !state.claiming) { Text("取消") } },
        )
    }
}

@Composable
private fun LeadSlaExceptionsPanel(
    stateValue: String?,
    todayOnly: Boolean = false,
    onOpen: (Long) -> Unit,
    viewModel: LeadSlaExceptionsViewModel,
) {
    val state by viewModel.state.collectAsState()
    LaunchedEffect(stateValue, todayOnly) { viewModel.load(stateValue, todayOnly) }
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text(
                when {
                    todayOnly -> "只展示今天到期的 SLA 待办，数据每次均从服务器刷新。"
                    stateValue == null -> "只展示需要处理的 SLA 异常，数据每次均从服务器刷新。"
                    else -> "当前筛选：${leadSlaStateLabel(stateValue)}"
                },
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        state.error?.let { error -> item { Text(error, color = MaterialTheme.colorScheme.error) } }
        if (state.loading) item { CircularProgressIndicator() }
        if (!state.loading && state.items.isEmpty()) item { Text("当前没有 SLA 异常") }
        items(state.items, key = { it.lead.id }) { row -> LeadSlaCard(row, onOpen) }
        if (state.items.size < state.total) item {
            TextButton(onClick = viewModel::loadMore, modifier = Modifier.fillMaxWidth()) {
                if (state.loadingMore) CircularProgressIndicator() else Text("加载更多")
            }
        }
    }
}

@Composable
private fun LeadSlaCard(row: LeadSlaException, onOpen: (Long) -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(row.lead.leadName, fontWeight = FontWeight.Bold)
                Text(leadSlaStateLabel(row.sla.state), color = MaterialTheme.colorScheme.error)
            }
            Text(row.lead.leadNo, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("阶段：${row.sla.phase ?: "待处理"} · 截止：${row.sla.deadline ?: "待安排"}")
            TextButton(onClick = { onOpen(row.lead.id) }) { Text("打开线索") }
        }
    }
}

data class LeadPublicPoolUiState(
    val query: String = "",
    val items: List<LeadPublicPoolRow> = emptyList(),
    val total: Int = 0,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val claiming: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class LeadPublicPoolViewModel @Inject constructor(
    private val repository: Round6Repository,
) : ViewModel() {
    private val mutableState = MutableStateFlow(LeadPublicPoolUiState())
    val state: StateFlow<LeadPublicPoolUiState> = mutableState.asStateFlow()

    fun updateQuery(query: String) {
        mutableState.value = mutableState.value.copy(query = query)
    }

    fun refresh() = load(reset = true)
    fun loadMore() = load(reset = false)

    fun claim(leadId: Long, onClaimed: (Long) -> Unit) {
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(claiming = true, error = null)
            runCatching { repository.claimLead(leadId) }
                .onSuccess { lead -> onClaimed(lead.id) }
                .onFailure { error -> mutableState.value = mutableState.value.copy(error = repository.errorMessage(error)) }
            mutableState.value = mutableState.value.copy(claiming = false)
        }
    }

    private fun load(reset: Boolean) {
        val current = mutableState.value
        if (!reset && (current.loadingMore || current.items.size >= current.total)) return
        viewModelScope.launch {
            mutableState.value = current.copy(loading = reset, loadingMore = !reset, error = if (reset) null else current.error)
            runCatching { repository.publicPool(query = current.query, offset = if (reset) 0 else current.items.size) }
                .onSuccess { page ->
                    mutableState.value = mutableState.value.copy(
                        items = if (reset) page.items else current.items + page.items,
                        total = page.total,
                        loading = false,
                        loadingMore = false,
                        error = null,
                    )
                }
                .onFailure { error -> mutableState.value = mutableState.value.copy(loading = false, loadingMore = false, error = repository.errorMessage(error)) }
        }
    }
}

data class LeadSlaExceptionsUiState(
    val stateValue: String? = null,
    val todayOnly: Boolean = false,
    val items: List<LeadSlaException> = emptyList(),
    val total: Int = 0,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class LeadSlaExceptionsViewModel @Inject constructor(
    private val repository: Round6Repository,
) : ViewModel() {
    private val mutableState = MutableStateFlow(LeadSlaExceptionsUiState())
    val state: StateFlow<LeadSlaExceptionsUiState> = mutableState.asStateFlow()

    fun load(stateValue: String?, todayOnly: Boolean = false) {
        if (mutableState.value.stateValue == stateValue && mutableState.value.todayOnly == todayOnly && mutableState.value.items.isNotEmpty()) return
        mutableState.value = LeadSlaExceptionsUiState(stateValue = stateValue, todayOnly = todayOnly)
        loadPage(reset = true)
    }

    fun loadMore() = loadPage(reset = false)

    private fun loadPage(reset: Boolean) {
        val current = mutableState.value
        if (!reset && (current.loadingMore || current.items.size >= current.total)) return
        viewModelScope.launch {
            mutableState.value = current.copy(loading = reset, loadingMore = !reset, error = if (reset) null else current.error)
            runCatching {
                repository.slaExceptions(
                    state = current.stateValue,
                    todayOnly = current.todayOnly,
                    offset = if (reset) 0 else current.items.size,
                )
            }
                .onSuccess { page ->
                    mutableState.value = mutableState.value.copy(
                        items = if (reset) page.items else current.items + page.items,
                        total = page.total,
                        loading = false,
                        loadingMore = false,
                        error = null,
                    )
                }
                .onFailure { error -> mutableState.value = mutableState.value.copy(loading = false, loadingMore = false, error = repository.errorMessage(error)) }
        }
    }
}
