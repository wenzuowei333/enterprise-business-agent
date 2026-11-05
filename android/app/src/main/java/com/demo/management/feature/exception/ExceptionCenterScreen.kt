package com.demo.management.feature.exception

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
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
import com.demo.designsystem.components.ContentSection
import com.demo.designsystem.components.LiquidActionButton
import com.demo.designsystem.components.LiquidBottomSheet
import com.demo.designsystem.components.LiquidDialog
import com.demo.designsystem.components.LiquidFilterChip
import com.demo.designsystem.components.LiquidSearchBar
import com.demo.designsystem.components.MetricStrip
import com.demo.designsystem.components.StatusTag
import com.demo.designsystem.components.StatusTone
import com.demo.management.data.MobileExceptionCase
import com.demo.management.data.MobileExceptionDetail
import com.demo.management.data.MobileAiActionProposal
import com.demo.management.data.MobileDiagnosisJob

@Composable
fun ExceptionCenterScreen(viewModel: ExceptionCenterViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    ExceptionCenterContent(
        state = state,
        onView = viewModel::setView,
        onQueryChange = viewModel::updateQuery,
        onSearch = viewModel::refresh,
        onDomain = viewModel::setDomain,
        onSeverity = viewModel::setSeverity,
        onStatus = viewModel::setStatus,
        onAssignment = viewModel::setAssignment,
        onLoadMore = viewModel::loadMore,
        onOpen = viewModel::open,
        onClose = viewModel::closeDetail,
        onDiagnose = viewModel::diagnose,
        onOpenAction = viewModel::openAction,
        onCloseAction = viewModel::closeAction,
        onValidateAction = viewModel::validateAction,
        onExecuteAction = viewModel::executeValidatedAction,
    )
}

@Composable
internal fun ExceptionCenterContent(
    state: ExceptionCenterUiState,
    onView: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onSearch: () -> Unit,
    onDomain: (String?) -> Unit,
    onSeverity: (String?) -> Unit,
    onStatus: (String?) -> Unit,
    onAssignment: (String?) -> Unit,
    onLoadMore: () -> Unit,
    onOpen: (String) -> Unit,
    onClose: () -> Unit,
    onDiagnose: (String) -> Unit,
    onOpenAction: (MobileAiActionProposal) -> Unit,
    onCloseAction: () -> Unit,
    onValidateAction: () -> Unit,
    onExecuteAction: () -> Unit,
) {
    var confirmExecution by remember { mutableStateOf(false) }
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                LiquidFilterChip(state.view == "cases", { onView("cases") }, Modifier.weight(1f)) { Text("异常案件") }
                if (state.capabilities.executeAction || state.actions.isNotEmpty()) {
                    LiquidFilterChip(state.view == "actions", { onView("actions") }, Modifier.weight(1f)) { Text("受控动作") }
                }
            }
        }
        if (state.view == "cases") item {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricStrip("待处置", (state.summary.open + state.summary.actionRequired).toString(), Modifier.weight(1f))
                MetricStrip("已阻塞", state.summary.blocked.toString(), Modifier.weight(1f))
                MetricStrip("已超期", state.summary.overdue.toString(), Modifier.weight(1f))
            }
        }
        if (state.view == "cases") item {
            LiquidSearchBar(
                value = state.query,
                onValueChange = onQueryChange,
                modifier = Modifier.fillMaxWidth(),
                placeholder = "搜索案件、资源编号或名称",
                onSearch = onSearch,
            )
        }
        if (state.view == "cases") item {
            FilterRow(
                selected = state.domain,
                values = listOf(null to "全部域", "inventory" to "库存", "master_data" to "主数据", "import" to "导入", "crm" to "CRM", "approval" to "审批"),
                onSelect = onDomain,
            )
        }
        if (state.view == "cases") item {
            FilterRow(
                selected = state.status,
                values = listOf(null to "全部状态", "open" to "待处理", "action_required" to "待行动", "processing" to "处理中", "blocked" to "阻塞", "resolved" to "已解决"),
                onSelect = onStatus,
            )
        }
        if (state.view == "cases") item {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(null to "全部级别", "critical" to "严重", "high" to "高", "warning" to "提醒").forEach { (key, label) ->
                    LiquidFilterChip(state.severity == key, { onSeverity(key) }) { Text(label) }
                }
                listOf(null to "全部归属", "mine" to "我的", "unassigned" to "未分配").forEach { (key, label) ->
                    LiquidFilterChip(state.assignment == key, { onAssignment(key) }) { Text(label) }
                }
            }
        }
        state.error?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
        if (state.view == "cases" && state.loading && state.items.isEmpty()) item { CircularProgressIndicator() }
        if (state.view == "cases" && !state.loading && state.items.isEmpty()) item { Text("当前筛选下暂无异常案件") }
        if (state.view == "cases") items(state.items, key = { it.caseNo }) { row -> ExceptionCaseRow(row) { onOpen(row.caseNo) } }
        if (state.view == "cases" && state.items.size < state.total) {
            item {
                TextButton(onClick = onLoadMore, modifier = Modifier.fillMaxWidth()) {
                    if (state.loadingMore) CircularProgressIndicator() else Text("加载更多")
                }
            }
        }
        if (state.view == "cases" && state.loadingDetail) item { Text("正在读取案件详情…", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        if (state.view == "actions") {
            item {
                Text("AI 提案必须重新校验证据，并由有权限的人员二次确认后执行。", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (state.loadingActions && state.actions.isEmpty()) item { CircularProgressIndicator() }
            if (!state.loadingActions && state.actions.isEmpty()) item { Text("当前没有待复核动作") }
            items(state.actions, key = { it.proposalNo }) { proposal ->
                ControlledActionRow(proposal) { onOpenAction(proposal) }
            }
        }
    }
    state.selected?.let { detail ->
        LiquidBottomSheet(onDismissRequest = onClose) {
            ExceptionDetailContent(
                detail = detail,
                job = state.diagnosisJob?.takeIf { it.caseNo == detail.caseNo },
                onDiagnose = { onDiagnose(detail.caseNo) },
            )
        }
    }
    state.selectedAction?.let { proposal ->
        LiquidBottomSheet(onDismissRequest = onCloseAction) {
            ControlledActionDetail(
                proposal = proposal,
                validation = state.actionValidation,
                executionStatus = state.actionExecution?.status,
                processing = state.processingAction,
                onValidate = onValidateAction,
                onRequestExecute = { confirmExecution = true },
            )
        }
    }
    if (confirmExecution && state.actionValidation != null) {
        LiquidDialog(
            onDismissRequest = { confirmExecution = false },
            title = { Text("确认执行受控动作") },
            text = { Text("系统将再次校验权限、证据版本和动作令牌。执行结果会写入审计日志，此操作不能由 AI 自动确认。") },
            confirmButton = {
                TextButton(onClick = { confirmExecution = false; onExecuteAction() }) { Text("人工确认执行") }
            },
            dismissButton = { TextButton(onClick = { confirmExecution = false }) { Text("取消") } },
        )
    }
}

@Composable
private fun FilterRow(selected: String?, values: List<Pair<String?, String>>, onSelect: (String?) -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        values.forEach { (key, label) -> LiquidFilterChip(selected == key, { onSelect(key) }) { Text(label) } }
    }
}

@Composable
private fun ExceptionCaseRow(row: MobileExceptionCase, onClick: () -> Unit) {
    ContentSection(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(row.title, modifier = Modifier.weight(1f), fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                StatusTag(exceptionStatusLabel(row.status), tone = exceptionStatusTone(row.status, row.severity))
            }
            Text("${exceptionDomainLabel(row.domain)} · ${row.caseNo}", color = MaterialTheme.colorScheme.primary)
            Text(row.reason, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(
                "${row.resourceName ?: row.resourceCode ?: "未关联具体对象"} · ${row.assigneeName ?: "未分配"}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun ExceptionDetailContent(detail: MobileExceptionDetail, job: MobileDiagnosisJob?, onDiagnose: () -> Unit) {
    LazyColumn(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("exception-detail-list")
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Text(
                detail.title,
                modifier = Modifier.testTag("exception-detail-title"),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
            )
            Text("${exceptionDomainLabel(detail.domain)} · ${detail.caseNo}", color = MaterialTheme.colorScheme.primary)
        }
        item { DetailLine("状态", exceptionStatusLabel(detail.status)) }
        item { DetailLine("异常原因", detail.reason) }
        item { DetailLine("初步建议", detail.initialGuidance ?: "等待人工研判") }
        item { DetailLine("关联对象", detail.resourceName ?: detail.resourceCode ?: "未关联具体对象") }
        item { DetailLine("负责人", detail.assigneeName ?: "未分配") }
        item { DetailLine("证据版本", detail.evidenceVersion) }
        if (detail.capabilities.diagnose && detail.diagnosisSupported) {
            item {
                val running = job?.status in setOf("queued", "processing")
                LiquidActionButton(onClick = onDiagnose, modifier = Modifier.fillMaxWidth(), enabled = !running) {
                    Text(if (running) "AI 正在诊断" else "发起 AI 诊断")
                }
            }
            if (job?.status in setOf("queued", "processing")) {
                item {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                        Text(
                            diagnosisProgressLabel(job?.status.orEmpty()),
                            modifier = Modifier.testTag("exception-diagnosis-progress"),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            if (job?.status == "failed") item { Text(job.errorMessage ?: "诊断失败，请稍后重试", color = MaterialTheme.colorScheme.error) }
        }
        detail.evidence?.takeIf { it.isNotEmpty() }?.let { evidence ->
            item { Text("当前证据", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
            items(evidence.entries.take(12).toList()) { (key, value) -> DetailLine(exceptionFieldLabel(key), exceptionValue(value)) }
        }
        if (detail.diagnoses.isNotEmpty()) {
            item { Text("诊断记录 ${detail.diagnoses.size}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
            items(detail.diagnoses.take(3)) { diagnosis ->
                DetailLine("诊断结果", exceptionValue(diagnosis["summary"] ?: diagnosis["root_cause"] ?: diagnosis["status"]))
            }
        }
        item {
            Text(
                "异常详情仅在线读取，不会保存到本机。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun ControlledActionRow(proposal: MobileAiActionProposal, onClick: () -> Unit) {
    ContentSection(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(actionLabel(proposal.actionType), modifier = Modifier.weight(1f), fontWeight = FontWeight.Bold)
                StatusTag(if (proposal.executable) "待确认" else "已阻断", tone = if (proposal.executable) StatusTone.Warning else StatusTone.Danger)
            }
            Text("${exceptionDomainLabel(proposal.domain)} · ${proposal.proposalNo}", color = MaterialTheme.colorScheme.primary)
            Text("案件：${proposal.resourceId ?: "-"}")
            if (proposal.blockers.isNotEmpty()) Text(proposal.blockers.joinToString("；", transform = ::blockerLabel), color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
private fun ControlledActionDetail(
    proposal: MobileAiActionProposal,
    validation: com.demo.management.data.MobileAiActionValidation?,
    executionStatus: String?,
    processing: Boolean,
    onValidate: () -> Unit,
    onRequestExecute: () -> Unit,
) {
    LazyColumn(modifier = Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Text(actionLabel(proposal.actionType), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
        item { DetailLine("提案编号", proposal.proposalNo) }
        item { DetailLine("关联案件", proposal.resourceId ?: "-") }
        item { DetailLine("风险等级", if (proposal.riskLevel == "high") "高风险" else "需人工复核") }
        if (proposal.blockers.isNotEmpty()) item { DetailLine("当前阻断", proposal.blockers.joinToString("；", transform = ::blockerLabel)) }
        validation?.proposal?.impact?.takeIf { it.isNotEmpty() }?.let { impact ->
            item { Text("执行影响", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
            items(impact.entries.take(10).toList()) { (key, value) -> DetailLine(exceptionFieldLabel(key), exceptionValue(value)) }
        }
        executionStatus?.let { item { DetailLine("执行结果", actionExecutionLabel(it)) } }
        if (executionStatus == null) {
            item {
                if (validation?.validationToken != null) {
                    LiquidActionButton(onClick = onRequestExecute, modifier = Modifier.fillMaxWidth(), enabled = !processing) {
                        Text(if (processing) "正在处理" else "确认影响并执行")
                    }
                } else {
                    LiquidActionButton(onClick = onValidate, modifier = Modifier.fillMaxWidth(), enabled = !processing && proposal.executable) {
                        Text(if (processing) "正在校验" else "重新校验证据与权限")
                    }
                }
            }
        }
        item { Text("校验令牌仅保存在当前页面内存中，关闭页面或执行后立即丢弃。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}

@Composable
private fun DetailLine(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value)
    }
}

internal fun exceptionStatusLabel(value: String): String = when (value) {
    "open" -> "待处理"
    "action_required" -> "待行动"
    "processing" -> "处理中"
    "blocked" -> "已阻塞"
    "resolved" -> "已解决"
    "ignored" -> "已忽略"
    else -> value
}

internal fun exceptionDomainLabel(value: String): String = when (value) {
    "inventory" -> "库存"
    "master_data" -> "主数据"
    "import" -> "导入"
    "receivable" -> "应收"
    "crm" -> "CRM"
    "approval" -> "审批"
    else -> value
}

private fun exceptionStatusTone(status: String, severity: String): StatusTone = when {
    status == "resolved" -> StatusTone.Success
    status == "processing" -> StatusTone.Info
    status == "blocked" || severity == "critical" -> StatusTone.Danger
    severity == "high" || status == "action_required" -> StatusTone.Warning
    else -> StatusTone.Neutral
}

internal fun exceptionFieldLabel(value: String): String = when (value) {
    "summary" -> "证据摘要"
    "observed" -> "观测值"
    "expected" -> "期望值"
    "difference" -> "差异"
    "data_date" -> "数据日期"
    else -> value.replace('_', ' ')
}

internal fun exceptionValue(value: Any?): String = when (value) {
    null -> "-"
    is Map<*, *> -> value.entries.take(8).joinToString("；") { "${it.key}:${exceptionValue(it.value)}" }
    is Iterable<*> -> value.take(8).joinToString("、") { exceptionValue(it) }
    else -> value.toString()
}

internal fun diagnosisProgressLabel(status: String): String = when (status) {
    "queued" -> "诊断已进入队列，正在等待安全执行资源"
    "processing" -> "正在核对证据并生成结构化中文诊断"
    "completed" -> "诊断已完成"
    "failed" -> "诊断失败"
    else -> "正在同步诊断状态"
}

internal fun actionLabel(value: String): String = when (value) {
    "rebuild_inventory_flow" -> "重建库存流转"
    "rerun_inventory_check" -> "重新执行库存核验"
    "rebuild_master_link_issues" -> "重建主数据关联检查"
    "revalidate_import_batch" -> "重新校验导入批次"
    "rebuild_receivable_checks" -> "重建应收核验"
    else -> value
}

private fun blockerLabel(value: String): String = when {
    value == "evidence_changed" -> "证据版本已变化"
    value == "source_batch_changed" -> "来源批次已变化"
    value == "action_disabled_by_policy" -> "动作未被策略开放"
    value.startsWith("missing_permission:") -> "缺少执行权限"
    value.startsWith("feature_disabled:") -> "服务端能力未开启"
    else -> value
}

private fun actionExecutionLabel(value: String): String = when (value) {
    "completed" -> "执行完成"
    "failed" -> "执行失败"
    "pending" -> "等待执行"
    "cancelled" -> "已取消"
    else -> value
}
