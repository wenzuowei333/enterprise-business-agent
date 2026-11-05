package com.demo.management.feature.collaboration

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.demo.designsystem.components.AppScaffold
import com.demo.designsystem.components.ContentSection
import com.demo.designsystem.components.LiquidIconButton
import com.demo.designsystem.components.LiquidTopBar
import com.demo.designsystem.components.StateLayout
import com.demo.designsystem.components.StateLayoutState
import com.demo.designsystem.components.StatusTag
import com.demo.designsystem.components.StatusTone
import com.demo.management.core.error.ApiErrorMapper
import com.demo.management.data.FieldCollaborationRepository
import com.demo.management.data.MobileCustomerTagPayload
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class CustomerTagsUiState(
    val loading: Boolean = false,
    val payload: MobileCustomerTagPayload? = null,
    val error: String? = null,
)

@HiltViewModel
class CustomerTagsViewModel @Inject constructor(
    private val repository: FieldCollaborationRepository,
) : ViewModel() {
    private val mutableState = MutableStateFlow(CustomerTagsUiState())
    val state: StateFlow<CustomerTagsUiState> = mutableState.asStateFlow()

    fun load(customerCode: String) {
        viewModelScope.launch {
            mutableState.value = CustomerTagsUiState(loading = true)
            runCatching { repository.customerTags(customerCode) }
                .onSuccess { mutableState.value = CustomerTagsUiState(payload = it) }
                .onFailure { mutableState.value = CustomerTagsUiState(error = ApiErrorMapper.fromThrowable(it)) }
        }
    }
}

@Composable
fun CustomerTagsScreen(
    customerCode: String,
    onClose: () -> Unit,
    viewModel: CustomerTagsViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    LaunchedEffect(customerCode) { viewModel.load(customerCode) }
    AppScaffold(
        topBar = {
            LiquidTopBar(
                title = { Text(state.payload?.customer?.customerName ?: "客户标签") },
                navigationIcon = {
                    LiquidIconButton(onClick = onClose) {
                        Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { padding ->
        StateLayout(
            state = when {
                state.loading -> StateLayoutState.Loading("正在读取标签")
                state.error != null -> StateLayoutState.Error(state.error.orEmpty())
                state.payload == null -> StateLayoutState.Empty("暂无标签数据")
                else -> StateLayoutState.Content
            },
            modifier = Modifier.fillMaxSize().padding(padding),
        ) {
            CustomerTagsContent(state.payload ?: return@StateLayout)
        }
    }
}

@Composable
internal fun CustomerTagsContent(payload: MobileCustomerTagPayload) {
    val grouped = payload.tags.items.groupBy { it.category ?: "其他" }
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Text("${payload.customer.customerCode} · 标签详情", color = MaterialTheme.colorScheme.primary)
            if (payload.tags.reviewDueCount > 0) {
                Text("${payload.tags.reviewDueCount} 项标签需要复核", color = MaterialTheme.colorScheme.error)
            }
        }
        grouped.forEach { (category, tags) ->
            item(key = "category:$category") {
                ContentSection(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(category, fontWeight = FontWeight.Bold)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            tags.forEach { tag ->
                                StatusTag(
                                    buildString {
                                        append(tag.name ?: "未命名标签")
                                        if (tag.isPrimary) append(" · 主标签")
                                    },
                                    tone = if (tag.reviewDate != null) StatusTone.Warning else StatusTone.Info,
                                )
                            }
                        }
                    }
                }
            }
        }
        if (grouped.isEmpty() && payload.tags.compatibilityTags.isEmpty()) {
            item { Text("当前客户暂无有效标签", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        if (payload.tags.compatibilityTags.isNotEmpty()) {
            item {
                ContentSection(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("历史兼容标签", fontWeight = FontWeight.Bold)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            payload.tags.compatibilityTags.forEach { StatusTag(it, tone = StatusTone.Neutral) }
                        }
                    }
                }
            }
        }
        item {
            Text(
                "本页标签详情仅在线读取，不新增本地缓存。标签变更继续在审批流程中完成。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
