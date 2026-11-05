package com.demo.management.feature.workbench

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.demo.designsystem.components.ContentSection
import com.demo.designsystem.components.LiquidActionButton
import com.demo.designsystem.components.LiquidOutlinedButton
import com.demo.designsystem.components.MetricStrip
import com.demo.designsystem.components.StatusTag
import com.demo.designsystem.components.StatusTone
import com.demo.management.data.WorkbenchPayload
import com.demo.management.data.WorkbenchQueueItem
import com.demo.management.data.WorkbenchTarget

@Composable
fun WorkbenchScreen(
    payload: WorkbenchPayload?,
    loading: Boolean,
    onCreateProject: () -> Unit,
    onOpenProjects: () -> Unit,
    onOpenApprovals: () -> Unit,
    onOpenWorkItems: () -> Unit,
    onTarget: (WorkbenchTarget) -> Unit,
) {
    if (loading && payload == null) {
        CircularProgressIndicator()
        return
    }

    val data = payload ?: WorkbenchPayload()
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .testTag("workbench-list"),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Text(data.dateLabel, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                data.headline.ifBlank { "今日工作台" },
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
            )
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                MetricStrip("进行中项目", data.summary.activeProjects.toString(), Modifier.weight(1f))
                MetricStrip("待审批", data.summary.pendingApprovals.toString(), Modifier.weight(1f))
            }
            Spacer(modifier = Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                MetricStrip("已超期", data.summary.overdueTasks.toString(), Modifier.weight(1f))
                MetricStrip("待支持", data.summary.openSupport.toString(), Modifier.weight(1f))
            }
        }

        if (data.shortcuts.createProject || data.shortcuts.viewApprovals || data.shortcuts.viewSupport) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (data.shortcuts.createProject) {
                        LiquidActionButton(onClick = onCreateProject, modifier = Modifier.fillMaxWidth()) { Text("申请项目") }
                    }
                    if (data.shortcuts.viewApprovals || data.shortcuts.viewSupport) {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                            if (data.shortcuts.viewApprovals) {
                                LiquidOutlinedButton(onClick = onOpenApprovals, modifier = Modifier.weight(1f)) { Text("审批中心") }
                            }
                            if (data.shortcuts.viewSupport) {
                                LiquidOutlinedButton(onClick = onOpenWorkItems, modifier = Modifier.weight(1f)) { Text("待支持") }
                            }
                        }
                    }
                }
            }
        }

        item { SectionTitle("今天要处理", "${data.todayQueue.total} 项") }
        if (data.todayQueue.items.isEmpty()) {
            item { EmptySection("今天暂无待处理事项") }
        } else {
            items(data.todayQueue.items, key = { it.key }) { item ->
                QueueRow(item = item, onClick = { onTarget(item.target) })
            }
        }

        item { SectionTitle("项目执行", if (data.projects.total > data.projects.items.size) "全部 ${data.projects.total}" else null, onClick = onOpenProjects) }
        if (data.projects.items.isEmpty()) {
            item { EmptySection("暂无进行中项目") }
        } else {
            items(data.projects.items, key = { "project:${it.id}" }) { project ->
                ContentSection(
                    modifier = Modifier.fillMaxWidth().clickable(onClick = onOpenProjects),
                ) {
                    Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                            Text(project.projectName, modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            StatusTag(if (project.overdue) "已逾期" else "进行中", tone = if (project.overdue) StatusTone.Danger else StatusTone.Info)
                        }
                        Text(
                            buildString {
                                append("待推进 ${project.openTasks}/${project.totalTasks}")
                                project.dueDate?.let { append(" · 截止 $it") }
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }

        if (data.approvals.items.isNotEmpty()) {
            item { SectionTitle("待审批申请", "去审批", onClick = onOpenApprovals) }
            items(data.approvals.items, key = { "approval:${it.id}" }) { approval ->
                ContentSection(modifier = Modifier.fillMaxWidth().clickable(onClick = onOpenApprovals)) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(14.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(approval.title, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            Text(approval.approvalNo, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        StatusTag("待审批", tone = StatusTone.Warning)
                    }
                }
            }
        }

        item { Spacer(modifier = Modifier.height(8.dp)) }
    }
}

@Composable
private fun SectionTitle(title: String, action: String? = null, onClick: (() -> Unit)? = null) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        if (action != null) {
            Text(
                action,
                modifier = if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier,
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@Composable
private fun QueueRow(item: WorkbenchQueueItem, onClick: () -> Unit) {
    ContentSection(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("workbench-queue-item:${item.key}")
            .clickable(onClick = onClick),
    ) {
        Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Text(item.title, modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                StatusTag(
                    item.statusLabel,
                    modifier = Modifier.testTag("workbench-queue-status:${item.key}"),
                    tone = item.tone.toStatusTone(),
                )
            }
            item.subtitle?.takeIf(String::isNotBlank)?.let {
                Spacer(modifier = Modifier.height(4.dp))
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
private fun EmptySection(text: String) {
    ContentSection(modifier = Modifier.fillMaxWidth()) {
        Text(text, modifier = Modifier.padding(18.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

internal fun String.toStatusTone(): StatusTone = when (this) {
    "bad" -> StatusTone.Danger
    "warn" -> StatusTone.Warning
    "good" -> StatusTone.Success
    "info" -> StatusTone.Info
    else -> StatusTone.Neutral
}

internal fun workbenchRoute(target: WorkbenchTarget): String? = when (target.page) {
    "projects", "tasks" -> "projects"
    "approvals" -> "approvals"
    "work_items" -> "work_items"
    else -> null
}
