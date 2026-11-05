package com.demo.management.feature.customer

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import com.demo.designsystem.components.ContentSection as Card
import com.demo.designsystem.components.LiquidActionButton as Button
import androidx.compose.material3.CircularProgressIndicator
import com.demo.designsystem.components.LiquidFilterChip as FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.demo.management.data.LinkedCustomerRow
import com.demo.management.core.ui.OfflineAccessGuard
import com.demo.designsystem.components.LiquidSearchBar
import com.demo.designsystem.components.StatusTag
import com.demo.designsystem.components.StatusTone

@Composable
fun CustomerScreen(
    onOpenCustomer: (String) -> Unit,
    canOpenCustomerDevelopment: Boolean = false,
    onCustomerDevelopment: () -> Unit = {},
    viewModel: CustomerViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    OfflineAccessGuard(offline = state.offline) {
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (canOpenCustomerDevelopment) item {
            Button(onClick = onCustomerDevelopment, modifier = Modifier.fillMaxWidth()) { Text("客户开发") }
        }
        item {
            LiquidSearchBar(
                value = state.query,
                onValueChange = viewModel::updateQuery,
                modifier = Modifier.fillMaxWidth(),
                placeholder = "搜索客户、项目、负责人或下一步动作",
                onSearch = viewModel::refresh,
            )
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(
                    listOf(null to "全部", "open" to "推进中", "support" to "待支持"),
                    listOf("risk" to "风险", "closed" to "已闭环"),
                ).forEach { filters ->
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        filters.forEach { (key, label) ->
                            FilterChip(selected = state.scope == key, onClick = { viewModel.setScope(key) }, label = { Text(label) })
                        }
                    }
                }
            }
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    SummaryCard("关联客户", state.summary.totalCustomers, Modifier.weight(1f))
                    SummaryCard("资料不完整", state.summary.profileIncomplete, Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    SummaryCard("待处理", state.summary.pendingActionCustomers, Modifier.weight(1f))
                    SummaryCard("风险", state.summary.riskCustomers, Modifier.weight(1f))
                }
            }
        }
        state.error?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
        if (state.loading) item { CircularProgressIndicator() }
        if (!state.loading && state.items.isEmpty()) item { Text("当前范围暂无关联客户") }
        items(state.items, key = { it.customerCode }) { row ->
            CustomerCard(row) { onOpenCustomer(row.customerCode) }
        }
        if (state.items.size < state.total) {
            item {
                TextButton(onClick = viewModel::loadMore, modifier = Modifier.fillMaxWidth()) {
                    if (state.loadingMore) CircularProgressIndicator() else Text("加载更多")
                }
            }
        }
    }
    }
}

@Composable
private fun CustomerCard(row: LinkedCustomerRow, onClick: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Text(row.customerName, fontWeight = FontWeight.Bold)
                StatusTag(
                    text = customerStatusLabel(row.latestTaskStatus),
                    tone = when {
                        row.taskBlocked > 0 -> StatusTone.Danger
                        row.taskNeedSupport > 0 -> StatusTone.Warning
                        row.latestTaskStatus in setOf("closed", "completed") -> StatusTone.Success
                        else -> StatusTone.Info
                    },
                )
            }
            Text(row.customerCode, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(listOfNotNull(row.customerType, row.region).joinToString(" · ").ifBlank { "类型/区域未填" })
            Text(listOfNotNull(row.contactName, row.contactPhone, row.customerGroupName).joinToString(" · ").ifBlank { "联系方式未补齐" })
            Text("负责人：${row.salespersonName ?: "未关联"} · 未闭环 ${row.taskOpen}")
            row.latestBlockerReason?.let { Text("卡点：$it", color = MaterialTheme.colorScheme.error) }
            Text("下一步：${row.latestOwnerNextAction ?: "待业务员补充"}", color = MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable
private fun SummaryCard(label: String, value: Int, modifier: Modifier) {
    Card(modifier = modifier) {
        Column(modifier = Modifier.padding(10.dp)) {
            Text(label, style = MaterialTheme.typography.labelSmall)
            Text(value.toString(), fontWeight = FontWeight.Bold)
        }
    }
}

private fun customerStatusLabel(value: String?): String = when (value) {
    "not_started" -> "未开始"
    "in_progress", "progressing" -> "推进中"
    "closed", "completed" -> "已闭环"
    else -> value ?: "待推进"
}
