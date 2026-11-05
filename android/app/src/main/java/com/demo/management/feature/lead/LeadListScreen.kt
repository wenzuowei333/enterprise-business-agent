package com.demo.management.feature.lead

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import com.demo.designsystem.components.LiquidActionButton as Button
import com.demo.designsystem.components.ContentSection as Card
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
import com.demo.management.data.round6.LeadRow
import com.demo.designsystem.components.LiquidSearchBar

@Composable
fun LeadListScreen(
    canCreate: Boolean,
    onCreate: () -> Unit,
    onOpen: (Long) -> Unit,
    viewModel: LeadListViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            LiquidSearchBar(
                value = state.query,
                onValueChange = viewModel::updateQuery,
                modifier = Modifier.fillMaxWidth(),
                placeholder = "搜索线索、公司、联系人或电话",
                onSearch = viewModel::refresh,
            )
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                leadStatusFilters()
                    .chunked(3)
                    .forEach { filters ->
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                            filters.forEach { (key, label) -> FilterChip(selected = state.status == key, onClick = { viewModel.setStatus(key) }, label = { Text(label) }) }
                        }
                    }
            }
        }
        if (canCreate) item { Button(onClick = onCreate, modifier = Modifier.fillMaxWidth()) { Text("新建客户线索") } }
        if (state.offline) item { Text("当前显示最近同步的离线线索", color = MaterialTheme.colorScheme.tertiary) }
        state.error?.let { error -> item { Text(error, color = MaterialTheme.colorScheme.error) } }
        if (state.loading) item { CircularProgressIndicator() }
        if (!state.loading && state.items.isEmpty()) item { Text("当前筛选条件下没有线索") }
        items(state.items, key = { it.id }) { lead -> LeadCard(lead, onOpen) }
        if (state.items.size < state.total) item {
            TextButton(onClick = viewModel::loadMore, modifier = Modifier.fillMaxWidth()) {
                if (state.loadingMore) CircularProgressIndicator() else Text("加载更多")
            }
        }
    }
}

@Composable
private fun LeadCard(lead: LeadRow, onOpen: (Long) -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().clickable { onOpen(lead.id) }) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Text(lead.leadName, fontWeight = FontWeight.Bold)
                Text(leadStatusLabel(lead.status), color = MaterialTheme.colorScheme.primary)
            }
            Text(lead.leadNo, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(listOfNotNull(lead.companyName, lead.contactName, lead.contactPhone).joinToString(" · ").ifBlank { "公司与联系人待补充" })
            Text(listOfNotNull(lead.source, lead.region, lead.businessLine).joinToString(" · ").ifBlank { "来源/区域未填" })
            Text("下次跟进：${lead.nextFollowupAt ?: "待安排"}", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

internal fun leadStatusLabel(status: String): String = when (status) {
    "new" -> "新建"
    "active" -> "跟进中"
    "qualified" -> "跟进中"
    "conversion_pending" -> "转化审批中"
    "converted" -> "已转客户"
    "closed" -> "已关闭"
    "rejected" -> "已驳回"
    else -> status
}

internal fun leadStatusFilters(): List<Pair<String?, String>> = listOf(
    null to "全部",
    "new" to "新建",
    "active" to "跟进中",
    "qualified" to "已合格",
    "conversion_pending" to "转化中",
    "converted" to "已转客户",
    "closed" to "已关闭",
    "rejected" to "已驳回",
)
