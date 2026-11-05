package com.demo.management.feature.customer

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.demo.designsystem.components.ContentSection
import com.demo.designsystem.components.LiquidFilterChip
import com.demo.designsystem.components.LiquidIconButton
import com.demo.designsystem.components.LiquidOutlinedButton
import com.demo.designsystem.components.LiquidTopBar
import com.demo.designsystem.components.MetricStrip
import com.demo.designsystem.components.StateLayout
import com.demo.designsystem.components.StateLayoutState
import com.demo.designsystem.components.StatusTag
import com.demo.designsystem.components.StatusTone
import com.demo.management.data.CustomerPanorama
import com.demo.management.data.CustomerTimelineItem
import com.demo.management.data.WorkbenchTarget

@Composable
fun CustomerPanoramaScreen(
    customerCode: String,
    onClose: () -> Unit,
    onEditProfile: (String) -> Unit,
    onEditBusinessProfile: (String) -> Unit,
    onTarget: (WorkbenchTarget) -> Unit,
    canOpenTags: Boolean = false,
    onOpenTags: (String) -> Unit = {},
    viewModel: CustomerPanoramaViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    LaunchedEffect(customerCode) { viewModel.load(customerCode) }

    CustomerPanoramaContent(
        state = state,
        onClose = onClose,
        onEditProfile = onEditProfile,
        onEditBusinessProfile = onEditBusinessProfile,
        onTarget = onTarget,
        canOpenTags = canOpenTags,
        onOpenTags = onOpenTags,
    )
}

@Composable
internal fun CustomerPanoramaContent(
    state: CustomerPanoramaUiState,
    onClose: () -> Unit,
    onEditProfile: (String) -> Unit,
    onEditBusinessProfile: (String) -> Unit,
    onTarget: (WorkbenchTarget) -> Unit,
    canOpenTags: Boolean = false,
    onOpenTags: (String) -> Unit = {},
) {
    var selectedTab by rememberSaveable { mutableStateOf("overview") }

    Column(modifier = Modifier.fillMaxSize()) {
        LiquidTopBar(
            title = { Text(state.panorama?.customer?.customerName ?: "客户全景") },
            navigationIcon = {
                LiquidIconButton(onClick = onClose) {
                    Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回")
                }
            },
        )
        StateLayout(
            state = when {
                state.loading -> StateLayoutState.Loading()
                state.error != null -> StateLayoutState.Error(state.error.orEmpty())
                state.panorama == null -> StateLayoutState.Empty("暂无客户数据")
                else -> StateLayoutState.Content
            },
            modifier = Modifier.fillMaxSize(),
        ) {
            val panorama = state.panorama ?: return@StateLayout
            Column(modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    listOf("overview" to "概览", "projects" to "项目任务", "timeline" to "时间线").forEach { (key, label) ->
                        LiquidFilterChip(
                            selected = selectedTab == key,
                            onClick = { selectedTab = key },
                            label = { Text(label) },
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
                Spacer(modifier = Modifier.height(10.dp))
                when (selectedTab) {
                    "projects" -> ProjectTaskContent(panorama, onTarget)
                    "timeline" -> TimelineContent(panorama.timeline, onTarget)
                    else -> OverviewContent(panorama, state.offline, onEditProfile, onEditBusinessProfile, canOpenTags, onOpenTags)
                }
            }
        }
    }
}

@Composable
private fun OverviewContent(
    panorama: CustomerPanorama,
    offline: Boolean,
    onEditProfile: (String) -> Unit,
    onEditBusinessProfile: (String) -> Unit,
    canOpenTags: Boolean,
    onOpenTags: (String) -> Unit,
) {
    val customer = panorama.customer
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (offline) item { StatusTag("离线数据", tone = StatusTone.Warning) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                MetricStrip("项目", (panorama.stats["project_total"] ?: panorama.projects.size).toString(), Modifier.weight(1f))
                MetricStrip("待推进", (panorama.stats["task_open"] ?: customer.taskOpen).toString(), Modifier.weight(1f))
            }
        }
        item {
            ContentSection(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    DetailLine("客户编号", customer.customerCode)
                    DetailLine("类型 / 区域", listOfNotNull(customer.customerType, customer.region).joinToString(" · ").ifBlank { "未填" })
                    DetailLine("联系人", listOfNotNull(customer.contactName, customer.contactPhone).joinToString(" · ").ifBlank { "未填" })
                    DetailLine("客户群", customer.customerGroupName ?: "未填")
                    DetailLine("详细地址", customer.address ?: "未填")
                    DetailLine("资料完整度", customer.baseInfoCompleteness ?: "待计算")
                }
            }
        }
        item {
            Text("客户标签", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            val names = (panorama.tags.items.mapNotNull { it.name } + panorama.tags.compatibilityTags).distinct()
            if (names.isEmpty()) {
                Text("暂无标签", color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    names.forEach { StatusTag(it, tone = StatusTone.Info) }
                }
            }
            if (!offline && canOpenTags) {
                Spacer(modifier = Modifier.height(8.dp))
                LiquidOutlinedButton(onClick = { onOpenTags(customer.customerCode) }, modifier = Modifier.fillMaxWidth()) {
                    Text("查看标签详情")
                }
            }
        }
        if (!offline && (panorama.capabilities.editProfile || panorama.capabilities.editBusinessProfile)) {
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    if (panorama.capabilities.editProfile) {
                        LiquidOutlinedButton(onClick = { onEditProfile(customer.customerCode) }, modifier = Modifier.weight(1f)) { Text("基本资料") }
                    }
                    if (panorama.capabilities.editBusinessProfile) {
                        LiquidOutlinedButton(onClick = { onEditBusinessProfile(customer.customerCode) }, modifier = Modifier.weight(1f)) { Text("经营资料") }
                    }
                }
            }
        }
        item { Spacer(modifier = Modifier.height(8.dp)) }
    }
}

@Composable
private fun ProjectTaskContent(panorama: CustomerPanorama, onTarget: (WorkbenchTarget) -> Unit) {
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Text("项目", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
        if (panorama.projects.isEmpty()) item { Text("暂无可见项目") }
        items(panorama.projects, key = { "project:${it.id}" }) { project ->
            ContentSection(modifier = Modifier.fillMaxWidth().clickable { onTarget(WorkbenchTarget(page = "projects", projectId = project.id)) }) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(project.projectName, fontWeight = FontWeight.SemiBold)
                    Text("待推进 ${project.taskOpen}/${project.taskTotal}${project.dueDate?.let { " · 截止 $it" }.orEmpty()}", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        item { Text("客户任务", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
        items(panorama.tasks, key = { "task:${it.id}" }) { task ->
            ContentSection(modifier = Modifier.fillMaxWidth().clickable { onTarget(WorkbenchTarget(page = "projects", taskId = task.id, projectId = task.projectId)) }) {
                Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(task.taskCode, fontWeight = FontWeight.SemiBold)
                        StatusTag(panoramaStatusLabel(task.status), tone = if (task.isBlocked) StatusTone.Danger else StatusTone.Info)
                    }
                    Text(task.latestOwnerNextAction ?: task.roundTarget ?: "待补充下一步动作", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
private fun TimelineContent(items: List<CustomerTimelineItem>, onTarget: (WorkbenchTarget) -> Unit) {
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (items.isEmpty()) item { Text("暂无业务时间线") }
        items(items, key = { it.key }) { item ->
            ContentSection(modifier = Modifier.fillMaxWidth().clickable { onTarget(item.target) }) {
                Row(modifier = Modifier.fillMaxWidth().padding(14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(item.title, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        item.detail?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis) }
                        item.occurredAt?.let { Text(it.take(10), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    }
                    item.status?.let { StatusTag(panoramaStatusLabel(it), tone = timelineTone(item.kind, it)) }
                }
            }
        }
    }
}

@Composable
private fun DetailLine(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.Top,
    ) {
        Text(
            label,
            modifier = Modifier.widthIn(min = 76.dp, max = 96.dp),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(modifier = Modifier.width(12.dp))
        Text(
            value,
            modifier = Modifier.weight(1f),
            maxLines = 3,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.End,
        )
    }
}

internal fun timelineTone(kind: String, status: String): StatusTone = when {
    status in setOf("rejected", "cancelled") -> StatusTone.Danger
    status in setOf("closed", "completed", "approved", "resolved") -> StatusTone.Success
    kind == "support" || status in setOf("need_support", "need_supplement") -> StatusTone.Warning
    else -> StatusTone.Info
}

internal fun panoramaStatusLabel(value: String): String = when (value) {
    "not_started" -> "未开始"
    "in_progress", "progressing", "active" -> "进行中"
    "submitted", "under_review", "pending" -> "待审批"
    "need_supplement" -> "待补充"
    "need_support" -> "待支持"
    "closed", "completed", "approved", "resolved" -> "已完成"
    "rejected" -> "已驳回"
    else -> value
}
