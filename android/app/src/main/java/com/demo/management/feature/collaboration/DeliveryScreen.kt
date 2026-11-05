package com.demo.management.feature.collaboration

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.designsystem.components.AppScaffold
import com.demo.designsystem.components.ContentSection
import com.demo.designsystem.components.LiquidActionButton
import com.demo.designsystem.components.LiquidBottomSheet
import com.demo.designsystem.components.LiquidDialog
import com.demo.designsystem.components.LiquidFilterChip
import com.demo.designsystem.components.LiquidIconButton
import com.demo.designsystem.components.LiquidSearchBar
import com.demo.designsystem.components.LiquidTopBar
import com.demo.designsystem.components.StatusTag
import com.demo.designsystem.components.StatusTone
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.FieldCollaborationRepository
import com.demo.management.data.MobileDeliveryCapabilities
import com.demo.management.data.MobileDeliveryTask
import com.demo.management.data.MobileDeliveryTransition
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class DeliveryUiState(
    val query: String = "",
    val status: String? = null,
    val items: List<MobileDeliveryTask> = emptyList(),
    val total: Int = 0,
    val capabilities: MobileDeliveryCapabilities = MobileDeliveryCapabilities(),
    val selected: MobileDeliveryTask? = null,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val submitting: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class DeliveryViewModel @Inject constructor(
    private val repository: FieldCollaborationRepository,
) : ViewModel() {
    private val mutableState = MutableStateFlow(DeliveryUiState())
    val state: StateFlow<DeliveryUiState> = mutableState.asStateFlow()

    init { refresh() }

    fun updateQuery(value: String) { mutableState.value = mutableState.value.copy(query = value) }
    fun setStatus(value: String?) { mutableState.value = mutableState.value.copy(status = value); refresh() }
    fun refresh() = load(reset = true)
    fun loadMore() = load(reset = false)
    fun open(delivery: MobileDeliveryTask) { mutableState.value = mutableState.value.copy(selected = delivery) }
    fun close() { mutableState.value = mutableState.value.copy(selected = null) }

    fun submit(transition: MobileDeliveryTransition, note: String, signedBy: String) {
        val delivery = mutableState.value.selected ?: return
        viewModelScope.launch {
            mutableState.value = mutableState.value.copy(submitting = true, error = null)
            runCatching { repository.addDeliveryEvent(delivery, transition, note, signedBy) }
                .onSuccess { updated ->
                    mutableState.value = mutableState.value.copy(
                        items = mutableState.value.items.map { if (it.id == updated.id) updated else it },
                        selected = updated,
                        submitting = false,
                    )
                }
                .onFailure { error -> showError(error) }
        }
    }

    private fun load(reset: Boolean) {
        val snapshot = mutableState.value
        if (snapshot.loading || snapshot.loadingMore) return
        viewModelScope.launch {
            mutableState.value = snapshot.copy(loading = reset, loadingMore = !reset, error = null)
            runCatching { repository.deliveries(snapshot.query, snapshot.status, if (reset) 0 else snapshot.items.size) }
                .onSuccess { page ->
                    mutableState.value = mutableState.value.copy(
                        items = if (reset) page.items else snapshot.items + page.items,
                        total = page.total,
                        capabilities = page.capabilities,
                        loading = false,
                        loadingMore = false,
                    )
                }
                .onFailure(::showError)
        }
    }

    private fun showError(error: Throwable) {
        mutableState.value = mutableState.value.copy(
            loading = false,
            loadingMore = false,
            submitting = false,
            error = ApiErrorMapper.fromThrowable(error),
        )
    }
}

@Composable
fun DeliveryScreen(onClose: (() -> Unit)? = null, viewModel: DeliveryViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    if (onClose == null) {
        DeliveryContent(
            state = state,
            modifier = Modifier.fillMaxSize(),
            onQuery = viewModel::updateQuery,
            onSearch = viewModel::refresh,
            onStatus = viewModel::setStatus,
            onLoadMore = viewModel::loadMore,
            onOpen = viewModel::open,
            onClose = viewModel::close,
            onSubmit = viewModel::submit,
        )
        return
    }
    AppScaffold(
        topBar = {
            LiquidTopBar(
                title = { Text("配送履约") },
                navigationIcon = { LiquidIconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } },
            )
        },
    ) { padding ->
        DeliveryContent(
            state = state,
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            onQuery = viewModel::updateQuery,
            onSearch = viewModel::refresh,
            onStatus = viewModel::setStatus,
            onLoadMore = viewModel::loadMore,
            onOpen = viewModel::open,
            onClose = viewModel::close,
            onSubmit = viewModel::submit,
        )
    }
}

@Composable
internal fun DeliveryContent(
    state: DeliveryUiState,
    modifier: Modifier = Modifier,
    onQuery: (String) -> Unit,
    onSearch: () -> Unit,
    onStatus: (String?) -> Unit,
    onLoadMore: () -> Unit,
    onOpen: (MobileDeliveryTask) -> Unit,
    onClose: () -> Unit,
    onSubmit: (MobileDeliveryTransition, String, String) -> Unit,
) {
    var transition by remember { mutableStateOf<MobileDeliveryTransition?>(null) }
    var note by remember { mutableStateOf("") }
    var signedBy by remember { mutableStateOf("") }
    LazyColumn(modifier = modifier, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            LiquidSearchBar(
                value = state.query,
                onValueChange = onQuery,
                modifier = Modifier.fillMaxWidth(),
                placeholder = "搜索配送单、订单或客户",
                onSearch = onSearch,
            )
        }
        item {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(null to "全部", "pending" to "待计划", "planned" to "已计划", "delivering" to "配送中", "exception" to "异常", "delivered" to "已签收").forEach { (key, label) ->
                    LiquidFilterChip(state.status == key, { onStatus(key) }) { Text(label) }
                }
            }
        }
        state.error?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
        if (state.loading && state.items.isEmpty()) item { CircularProgressIndicator() }
        if (!state.loading && state.items.isEmpty()) item { Text("当前筛选下暂无配送任务") }
        items(state.items, key = { it.id }) { item -> DeliveryRow(item) { onOpen(item) } }
        if (state.items.size < state.total) item {
            TextButton(onClick = onLoadMore, modifier = Modifier.fillMaxWidth()) {
                if (state.loadingMore) CircularProgressIndicator() else Text("加载更多")
            }
        }
        item { Text("配送任务和事件仅在线读取，不会保存到本机。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
    state.selected?.let { selected ->
        LiquidBottomSheet(onDismissRequest = onClose) {
            DeliveryDetail(
                delivery = selected,
                canManage = state.capabilities.manage,
                submitting = state.submitting,
                error = state.error,
                onTransition = { transition = it; note = ""; signedBy = "" },
            )
        }
    }
    transition?.let { target ->
        LiquidDialog(
            onDismissRequest = { if (!state.submitting) transition = null },
            title = { Text(target.label) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("提交时会校验配送任务最新版本，重复点击不会重复生成履约事件。")
                    if (target.requiresNote) {
                        OutlinedTextField(value = note, onValueChange = { note = it }, label = { Text("处理说明") }, minLines = 2)
                    }
                    if (target.requiresSignature) {
                        OutlinedTextField(value = signedBy, onValueChange = { signedBy = it }, label = { Text("签收人") }, singleLine = true)
                    }
                }
            },
            confirmButton = {
                TextButton(
                    enabled = !state.submitting && (!target.requiresNote || note.isNotBlank()) && (!target.requiresSignature || signedBy.isNotBlank()),
                    onClick = { onSubmit(target, note, signedBy); transition = null },
                ) { Text("人工确认") }
            },
            dismissButton = { TextButton(onClick = { transition = null }, enabled = !state.submitting) { Text("取消") } },
        )
    }
}

@Composable
private fun DeliveryRow(delivery: MobileDeliveryTask, onClick: () -> Unit) {
    ContentSection(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(delivery.customerName ?: delivery.customerCode ?: "未关联客户", modifier = Modifier.weight(1f), fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                StatusTag(deliveryStatusLabel(delivery.status), tone = deliveryStatusTone(delivery.status))
            }
            Text("${delivery.deliveryNo}${delivery.orderNo?.let { " · $it" }.orEmpty()}", color = MaterialTheme.colorScheme.primary)
            Text(delivery.deliveryAddress ?: "配送地址待补充", maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text("计划：${delivery.plannedAt ?: "待安排"}", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun DeliveryDetail(
    delivery: MobileDeliveryTask,
    canManage: Boolean,
    submitting: Boolean,
    error: String?,
    onTransition: (MobileDeliveryTransition) -> Unit,
) {
    LazyColumn(modifier = Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Text(
                delivery.customerName ?: delivery.deliveryNo,
                modifier = Modifier.testTag("delivery-detail-title"),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
            )
        }
        item { Text("${delivery.deliveryNo} · ${deliveryStatusLabel(delivery.status)}", color = MaterialTheme.colorScheme.primary) }
        item { DeliveryLine("配送地址", delivery.deliveryAddress ?: "待补充") }
        item { DeliveryLine("计划时间", delivery.plannedAt ?: "待安排") }
        delivery.exceptionNote?.let { item { DeliveryLine("异常说明", it) } }
        delivery.signedBy?.let { item { DeliveryLine("签收", "$it · ${delivery.signedAt ?: "时间待同步"}") } }
        error?.let {
            item {
                Text(
                    it,
                    modifier = Modifier.testTag("delivery-detail-error"),
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
        if (delivery.requirements.isNotEmpty()) {
            item { Text("配送要求", fontWeight = FontWeight.Bold) }
            items(delivery.requirements.take(12)) { requirement ->
                Text("• ${requirement["tag_name"] ?: "配送要求"}${requirement["source_type"]?.let { " · $it" }.orEmpty()}")
            }
        }
        if (canManage) {
            items(deliveryTransitions(delivery.status), key = { "${it.eventType}:${it.toStatus}" }) { target ->
                LiquidActionButton(onClick = { onTransition(target) }, modifier = Modifier.fillMaxWidth(), enabled = !submitting) { Text(target.label) }
            }
        }
        if (delivery.events.isNotEmpty()) {
            item { Text("履约时间线", fontWeight = FontWeight.Bold) }
            items(delivery.events.takeLast(12).reversed(), key = { it.id }) { event ->
                DeliveryLine(deliveryStatusLabel(event.toStatus.orEmpty()), listOfNotNull(event.createdAt.take(16), event.note).joinToString(" · "))
            }
        }
    }
}

@Composable
private fun DeliveryLine(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value)
    }
}

internal fun deliveryStatusLabel(value: String): String = when (value) {
    "pending" -> "待计划"
    "planned" -> "已计划"
    "delivering" -> "配送中"
    "delivered" -> "已签收"
    "exception" -> "配送异常"
    "cancelled" -> "已取消"
    else -> value
}

private fun deliveryStatusTone(value: String): StatusTone = when (value) {
    "delivered" -> StatusTone.Success
    "delivering" -> StatusTone.Info
    "exception", "cancelled" -> StatusTone.Danger
    "planned" -> StatusTone.Warning
    else -> StatusTone.Neutral
}
