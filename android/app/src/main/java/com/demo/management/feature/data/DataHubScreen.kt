package com.demo.management.feature.data

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import com.demo.designsystem.components.LiquidActionButton as Button
import com.demo.designsystem.components.LiquidDialog as AlertDialog
import com.demo.designsystem.components.ContentSection as Card
import androidx.compose.material3.CircularProgressIndicator
import com.demo.designsystem.components.LiquidFilterChip as FilterChip
import androidx.compose.material3.MaterialTheme
import com.demo.designsystem.components.LiquidOutlinedButton as OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.heightIn
import androidx.hilt.navigation.compose.hiltViewModel
import com.demo.management.data.round3.DashboardOverview
import com.demo.management.data.round3.InventoryCheckBatch
import com.demo.designsystem.components.LiquidSearchBar

@Composable
fun DataHubScreen(
    featureFlags: Map<String, Boolean>,
    isAdmin: Boolean,
    onScan: () -> Unit,
    onOpenData: (String, String) -> Unit,
    initialModule: String? = null,
    initialQuery: String? = null,
    viewModel: DataHubViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    LaunchedEffect(initialModule, initialQuery) { viewModel.applyDeepLink(initialModule, initialQuery) }
    val sections = visibleDataSections(state.modules.map { it.key }.toSet(), featureFlags, isAdmin)
    Column(modifier = Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            sections.forEach { key ->
                FilterChip(
                    selected = state.section == key,
                    onClick = { viewModel.setSection(key) },
                    label = { Text(sectionLabel(key)) },
                )
            }
            if (featureFlags["scanner"] == true) OutlinedButton(onClick = onScan) { Text("扫码") }
        }
        Spacer(modifier = Modifier.height(10.dp))
        state.error?.let { MessageCard(it, true, viewModel::clearMessage) }
        state.notice?.let { MessageCard(it, false, viewModel::clearMessage) }
        when (state.section) {
            "checks" -> ChecksSection(state, viewModel, onOpenData)
            "dashboard" -> DashboardSection(state.dashboard, state.dashboardRange, state.loading, viewModel::setDashboardRange)
            "ai" -> AssistantSection(state, viewModel)
            else -> QuerySection(state, viewModel, onOpenData)
        }
    }
}

@Composable
private fun QuerySection(state: DataHubUiState, viewModel: DataHubViewModel, onOpenData: (String, String) -> Unit) {
    var detail by remember { mutableStateOf<Pair<String, Map<String, Any?>>?>(null) }
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row(modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                state.modules.filter { it.key !in setOf("inventory_check", "receivable_check") }.forEach { module ->
                    FilterChip(selected = state.selectedModule == module.key, onClick = { viewModel.selectModule(module.key) }, label = { Text(module.label) })
                }
            }
        }
        item {
            LiquidSearchBar(
                value = state.query,
                onValueChange = viewModel::updateQuery,
                modifier = Modifier.fillMaxWidth(),
                placeholder = "搜索编号或名称",
                onSearch = viewModel::refreshData,
            )
        }
        if (state.selectedModule !in setOf("customers", "products", "suppliers")) {
            item {
                Row(modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("today" to "今日", "yesterday" to "昨日", "7d" to "近7天", "month" to "本月").forEach { (key, label) ->
                        FilterChip(selected = false, onClick = { viewModel.applyDatePreset(key) }, label = { Text(label) })
                    }
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedTextField(value = state.dateFrom, onValueChange = viewModel::updateDateFrom, modifier = Modifier.weight(1f), label = { Text("开始日期") }, singleLine = true)
                    OutlinedTextField(value = state.dateTo, onValueChange = viewModel::updateDateTo, modifier = Modifier.weight(1f), label = { Text("结束日期") }, singleLine = true)
                }
            }
            if (state.selectedModule in setOf("sales", "purchases", "inventory")) item {
                OutlinedTextField(value = state.warehouse, onValueChange = viewModel::updateWarehouse, modifier = Modifier.fillMaxWidth(), label = { Text("仓库") }, singleLine = true)
            }
        }
        item { SummaryStrip(state.total, state.summary) }
        if (state.loading && state.items.isEmpty()) item { CircularProgressIndicator() }
        if (!state.loading && state.items.isEmpty()) item { Text("当前筛选暂无数据") }
        items(state.items) { row -> RecordCard(state.selectedModule.orEmpty(), row) { detail = state.selectedModule.orEmpty() to row } }
        if (state.items.size < state.total) item {
            TextButton(onClick = viewModel::loadMoreData, modifier = Modifier.fillMaxWidth()) {
                if (state.loadingMore) CircularProgressIndicator() else Text("加载更多")
            }
        }
    }
    detail?.let { (module, row) -> RecordDetailDialog(module, row, onDismiss = { detail = null }, onOpenData = onOpenData) }
}

@Composable
private fun ChecksSection(state: DataHubUiState, viewModel: DataHubViewModel, onOpenData: (String, String) -> Unit) {
    var detail by remember { mutableStateOf<Pair<String, Map<String, Any?>>?>(null) }
    val inventoryPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? -> uri?.let(viewModel::uploadInventory) }
    val receivablePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? -> uri?.let(viewModel::uploadReceivable) }
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = state.checkKind == "inventory", onClick = { viewModel.setCheckKind("inventory") }, label = { Text("库存核验") })
                FilterChip(selected = state.checkKind == "receivable", onClick = { viewModel.setCheckKind("receivable") }, label = { Text("应收校验") })
            }
        }
        item { OutlinedTextField(value = state.checkDate, onValueChange = viewModel::updateCheckDate, modifier = Modifier.fillMaxWidth(), label = { Text("核验日期（留空自动识别）") }, singleLine = true) }
        item {
            Button(
                onClick = {
                    val types = arrayOf("text/csv", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    if (state.checkKind == "inventory") inventoryPicker.launch(types) else receivablePicker.launch(types)
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = !state.loading,
            ) { Text(if (state.checkKind == "inventory") "上传实时库存表" else "上传应收查询表") }
        }
        if (state.checkKind == "receivable") {
            state.receivableBatch?.let { batch ->
                item {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(batch.fileName, fontWeight = FontWeight.Bold)
                            Text("识别日期 ${batch.dataDate ?: "待确认"} · ${batch.status}")
                            Text("总行 ${batch.totalRows} · 错误 ${batch.errorRows}")
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedButton(onClick = viewModel::validateReceivable, enabled = batch.status !in setOf("validated", "committed")) { Text("预校验") }
                                Button(onClick = viewModel::commitReceivable, enabled = batch.status == "validated") { Text("确认提交") }
                            }
                        }
                    }
                }
            }
        } else {
            item { Text("核验时间线", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
            items(state.inventoryBatches, key = { it.id }) { batch -> InventoryBatchCard(batch, state.selectedInventoryBatch?.id == batch.id) { viewModel.openInventoryBatch(batch) } }
        }
        item {
            OutlinedTextField(
                value = state.checkQuery,
                onValueChange = viewModel::updateCheckQuery,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(if (state.checkKind == "inventory") "搜索商品编号或名称" else "搜索结算单位") },
                singleLine = true,
                trailingIcon = { TextButton(onClick = viewModel::refreshCheckResults) { Text("搜索") } },
            )
        }
        item {
            Row(modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                checkTypeOptions(state.checkKind).forEach { (key, label) ->
                    FilterChip(selected = state.checkResultType == key, onClick = { viewModel.setCheckResultType(key) }, label = { Text(label) })
                }
            }
        }
        item { SummaryStrip(state.checkTotal, state.summary) }
        if (state.loading) item { CircularProgressIndicator() }
        items(state.checkItems) { row ->
            val module = if (state.checkKind == "inventory") "inventory_check" else "receivable_check"
            RecordCard(module, row) { detail = module to row }
        }
        if (state.checkItems.size < state.checkTotal) item {
            TextButton(onClick = viewModel::loadMoreCheckResults, modifier = Modifier.fillMaxWidth()) {
                if (state.loadingMore) CircularProgressIndicator() else Text("加载更多差异")
            }
        }
    }
    detail?.let { (module, row) -> RecordDetailDialog(module, row, onDismiss = { detail = null }, onOpenData = onOpenData) }
}

@Composable
private fun DashboardSection(dashboard: DashboardOverview?, range: String, loading: Boolean, onRange: (String) -> Unit) {
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("today" to "今日", "7d" to "7天", "30d" to "30天", "month" to "本月").forEach { (key, label) -> FilterChip(selected = range == key, onClick = { onRange(key) }, label = { Text(label) }) }
            }
        }
        if (loading && dashboard == null) item { CircularProgressIndicator() }
        dashboard?.let { data ->
            item { Text(data.conclusion ?: "经营数据已刷新", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
            items(data.metrics) { metric -> RecordCard("metric", metric) }
            item { TrendChart(data.trend) }
            item { Text("风险与行动", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
            items(data.actions.take(5)) { action -> RecordCard("action", action) }
        }
    }
}

@Composable
private fun AssistantSection(state: DataHubUiState, viewModel: DataHubViewModel) {
    Column(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("管理员只读 AI", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Text("可分析经营风险与项目进度，不会直接修改业务数据。", color = MaterialTheme.colorScheme.onSurfaceVariant)
        LazyColumn(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(state.assistantMessages) { message -> Card(modifier = Modifier.fillMaxWidth()) { Text(message, modifier = Modifier.padding(12.dp)) } }
        }
        OutlinedTextField(value = state.assistantInput, onValueChange = viewModel::updateAssistantInput, modifier = Modifier.fillMaxWidth(), label = { Text("输入分析问题") }, minLines = 2)
        Button(onClick = viewModel::sendAssistantMessage, modifier = Modifier.fillMaxWidth(), enabled = !state.loading && state.assistantInput.isNotBlank()) { Text("生成分析") }
    }
}

@Composable
private fun RecordCard(module: String, row: Map<String, Any?>, onClick: (() -> Unit)? = null) {
    val title = firstText(row, titleKeys(module)) ?: "数据记录"
    val subtitle = firstText(row, codeKeys(module))
    val excluded = (titleKeys(module) + codeKeys(module)).toSet()
    val details = row.entries.filter { it.key !in excluded && it.value != null && it.value.toString().isNotBlank() }.take(5)
    Card(modifier = Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
            subtitle?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
            details.forEach { (key, value) -> Text("${fieldLabel(key)}：${displayValue(value)}", maxLines = 2, overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }
}

@Composable
private fun RecordDetailDialog(
    module: String,
    row: Map<String, Any?>,
    onDismiss: () -> Unit,
    onOpenData: (String, String) -> Unit,
) {
    val links = relatedRecordLinks(row)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(firstText(row, titleKeys(module)) ?: "记录详情") },
        text = {
            Column(modifier = Modifier.heightIn(max = 440.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                row.entries.filter { it.value != null && it.value.toString().isNotBlank() }.forEach { (key, value) ->
                    Column {
                        Text(fieldLabel(key), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(displayValue(value))
                    }
                }
                if (links.isNotEmpty()) {
                    Text("关联查看", fontWeight = FontWeight.Bold)
                    Row(modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        links.forEach { link -> OutlinedButton(onClick = { onDismiss(); onOpenData(link.module, link.query) }) { Text(link.label) } }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
    )
}

@Composable
private fun InventoryBatchCard(batch: InventoryCheckBatch, selected: Boolean, onClick: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(batch.fileName, fontWeight = FontWeight.Bold, color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
            Text("${batch.dataDate ?: "未识别日期"} · 差异 ${batch.differenceRows} · 匹配 ${batch.matchedRows}")
            Text("总行 ${batch.totalRows} · 无效 ${batch.invalidRows} · 缺基准 ${batch.missingInSystemRows}", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun SummaryStrip(total: Int, summary: Map<String, Any?>) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text("共 $total 条", fontWeight = FontWeight.Bold)
            if (summary.isNotEmpty()) Text(summary.entries.take(4).joinToString(" · ") { "${fieldLabel(it.key)} ${displayValue(it.value)}" }, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2)
        }
    }
}

@Composable
private fun TrendChart(rows: List<Map<String, Any?>>) {
    val values = rows.mapNotNull { (it["sales_amount"] as? Number)?.toFloat() }
    val lineColor = MaterialTheme.colorScheme.primary
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text("销售趋势", fontWeight = FontWeight.Bold)
            Spacer(modifier = Modifier.height(10.dp))
            Canvas(modifier = Modifier.fillMaxWidth().height(150.dp)) {
                if (values.size > 1) {
                    val max = values.maxOrNull()?.takeIf { it > 0f } ?: 1f
                    val path = Path()
                    values.forEachIndexed { index, value ->
                        val point = Offset(size.width * index / (values.size - 1), size.height - size.height * value / max)
                        if (index == 0) path.moveTo(point.x, point.y) else path.lineTo(point.x, point.y)
                    }
                    drawPath(path, lineColor, style = Stroke(width = 5f, cap = StrokeCap.Round))
                }
            }
        }
    }
}

@Composable
private fun MessageCard(message: String, error: Boolean, onDismiss: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().clickable(onClick = onDismiss)) {
        Text(message, modifier = Modifier.padding(12.dp), color = if (error) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
    }
}

private fun sectionLabel(key: String) = when (key) {
    "checks" -> "数据核验"
    "dashboard" -> "经营看板"
    "ai" -> "AI 分析"
    else -> "业务查询"
}
private fun checkTypeOptions(kind: String): List<Pair<String, String>> = if (kind == "inventory") listOf(
    "" to "全部差异",
    "quantity_mismatch" to "数量不一致",
    "missing_in_system" to "系统缺基准",
    "invalid_row" to "无效行",
) else listOf(
    "" to "全部差异",
    "amount_mismatch" to "金额不一致",
    "missing_in_ledger" to "往来缺失",
    "missing_in_receivable_query" to "查询表缺失",
    "unit_name_mismatch" to "名称不一致",
    "duplicate_unit" to "重复单位",
)
private fun titleKeys(module: String) = when (module) {
    "customers" -> listOf("customer_name")
    "products", "inventory", "inventory_check" -> listOf("product_name")
    "suppliers" -> listOf("supplier_name")
    "sales" -> listOf("customer_name", "product_name")
    "purchases" -> listOf("supplier_name", "product_name")
    "account_ledger", "receivable_check" -> listOf("settlement_unit_name", "customer_name")
    "metric", "action" -> listOf("label", "title")
    else -> listOf("title", "name")
}
private fun codeKeys(module: String) = when (module) {
    "customers" -> listOf("customer_code")
    "products", "inventory", "inventory_check" -> listOf("product_code")
    "suppliers" -> listOf("supplier_code")
    "sales", "purchases" -> listOf("document_no", "product_code")
    "account_ledger", "receivable_check" -> listOf("settlement_unit_code", "customer_code")
    else -> listOf("key", "date")
}
private fun firstText(row: Map<String, Any?>, keys: List<String>): String? = keys.firstNotNullOfOrNull { row[it]?.toString()?.takeIf(String::isNotBlank) }
private fun displayValue(value: Any?): String = when (value) { is Double -> "%.2f".format(value); is Float -> "%.2f".format(value); is List<*> -> value.joinToString("、"); is Map<*, *> -> value.entries.take(3).joinToString("、") { "${it.key}:${it.value}" }; else -> value?.toString() ?: "-" }
private fun fieldLabel(key: String): String = mapOf(
    "customer_name" to "客户", "product_name" to "商品", "supplier_name" to "供应商", "warehouse_name" to "仓库",
    "document_date" to "单据日期", "data_date" to "数据日期", "amount_tax_total" to "销售额", "purchase_amount" to "采购额",
    "stock_qty" to "库存", "locked_qty" to "锁定", "result_type" to "差异类型", "diff_qty" to "差异",
    "ar_amount" to "应收查询", "ledger_ar_amount" to "往来应收", "value" to "数值",
)[key] ?: key.replace('_', ' ')
