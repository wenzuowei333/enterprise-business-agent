package com.demo.management.feature.task

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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import com.demo.designsystem.components.LiquidFilterChip
import com.demo.designsystem.components.LiquidSearchBar
import com.demo.designsystem.components.MetricStrip
import com.demo.designsystem.components.StatusTag
import com.demo.designsystem.components.StatusTone
import com.demo.management.core.ui.OfflineAccessGuard
import com.demo.management.data.CrmTaskDetail
import com.demo.management.data.CrmTaskRow
import com.demo.management.data.ExecutionProject

@Composable
fun TaskScreen(
    onFollowup: (Long) -> Unit,
    onCreateProject: () -> Unit,
    canOpenDeliveries: Boolean = false,
    onOpenDeliveries: () -> Unit = {},
    viewModel: TaskViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    TaskContent(
        state = state,
        onSetView = viewModel::setView,
        onQueryChange = viewModel::updateQuery,
        onProjectFilter = viewModel::setProjectFilter,
        onTaskFilter = viewModel::setTaskFilter,
        onRefresh = viewModel::refresh,
        onOpenTask = viewModel::open,
        onCloseTask = viewModel::closeDetail,
        onFollowup = onFollowup,
        onCreateProject = onCreateProject,
        canOpenDeliveries = canOpenDeliveries,
        onOpenDeliveries = onOpenDeliveries,
    )
}

@Composable
internal fun TaskContent(
    state: TaskUiState,
    onSetView: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onProjectFilter: (String) -> Unit,
    onTaskFilter: (String) -> Unit,
    onRefresh: () -> Unit,
    onOpenTask: (Long) -> Unit,
    onCloseTask: () -> Unit,
    onFollowup: (Long) -> Unit,
    onCreateProject: () -> Unit,
    canOpenDeliveries: Boolean = false,
    onOpenDeliveries: () -> Unit = {},
) {
    var selectedProject by remember { mutableStateOf<ExecutionProject?>(null) }
    val payload = state.payload
    val projects = filterExecutionProjects(payload.projects.items, state.query, state.projectFilter)
    val tasks = filterExecutionTasks(payload.myTasks.items, state.query, state.taskFilter)

    OfflineAccessGuard(offline = state.offline) {
        LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    LiquidFilterChip(state.view == "projects", { onSetView("projects") }, Modifier.weight(1f)) { Text("项目执行") }
                    LiquidFilterChip(state.view == "tasks", { onSetView("tasks") }, Modifier.weight(1f)) { Text("我的工作") }
                    if (canOpenDeliveries) {
                        LiquidFilterChip(false, onOpenDeliveries, Modifier.weight(1f)) { Text("配送履约") }
                    }
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    if (state.view == "projects") {
                        MetricStrip("进行中", payload.summary.activeProjects.toString(), Modifier.weight(1f))
                        MetricStrip("超期项目", payload.summary.overdueProjects.toString(), Modifier.weight(1f))
                    } else {
                        MetricStrip("待推进", payload.summary.myOpenTasks.toString(), Modifier.weight(1f))
                        MetricStrip("超期 / 阻塞", "${payload.summary.overdueTasks} / ${payload.summary.blockedTasks}", Modifier.weight(1f))
                    }
                }
            }
            if (state.view == "projects" && payload.capabilities.createProject && !state.offline) {
                item { LiquidActionButton(onClick = onCreateProject, modifier = Modifier.fillMaxWidth()) { Text("申请新项目") } }
            }
            item {
                LiquidSearchBar(
                    value = state.query,
                    onValueChange = onQueryChange,
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = if (state.view == "projects") "搜索项目名称、编号或目标" else "搜索客户、任务或下一步动作",
                    onSearch = onRefresh,
                )
            }
            item {
                val filters = if (state.view == "projects") {
                    listOf("active" to "进行中", "overdue" to "已超期", "closed" to "已完成", "all" to "全部")
                } else {
                    listOf("open" to "待推进", "support" to "待支持", "blocked" to "阻塞", "overdue" to "超期", "closed" to "已闭环")
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    filters.forEach { (key, label) ->
                        LiquidFilterChip(
                            selected = if (state.view == "projects") state.projectFilter == key else state.taskFilter == key,
                            onClick = { if (state.view == "projects") onProjectFilter(key) else onTaskFilter(key) },
                        ) { Text(label) }
                    }
                }
            }
            state.error?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
            if (state.loading) item { CircularProgressIndicator() }
            if (!state.loading && state.view == "projects" && projects.isEmpty()) item { Text("当前筛选下暂无项目") }
            if (!state.loading && state.view == "tasks" && tasks.isEmpty()) item { Text("当前筛选下暂无个人任务") }
            if (state.view == "projects") {
                items(projects, key = { "project:${it.id}" }) { project -> ProjectCard(project) { selectedProject = project } }
            } else {
                items(tasks, key = { "task:${it.id}" }) { task -> TaskCard(task) { onOpenTask(task.id) } }
            }
        }
    }
    selectedProject?.let { project ->
        LiquidBottomSheet(onDismissRequest = { selectedProject = null }) { ProjectDetail(project) }
    }
    state.selected?.let { detail ->
        LiquidBottomSheet(onDismissRequest = onCloseTask) {
            TaskDetail(
                detail = detail,
                canSubmitFollowup = state.payload.capabilities.submitFollowup && !state.offline,
                onFollowup = onFollowup,
            )
        }
    }
}

@Composable
private fun ProjectCard(project: ExecutionProject, onClick: () -> Unit) {
    ContentSection(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Text(project.projectName, modifier = Modifier.weight(1f), fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                StatusTag(projectStatusLabel(project), tone = if (project.overdue) StatusTone.Danger else if (project.status == "closed") StatusTone.Success else StatusTone.Info)
            }
            Text("${project.projectCode}${project.projectType?.let { " · $it" }.orEmpty()}", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("任务 ${project.taskOpen}/${project.taskTotal} 待推进 · 待支持 ${project.taskNeedSupport} · 阻塞 ${project.taskBlocked}")
            Text("截止：${project.dueDate ?: "未设置"}")
            Text("下一步：${project.nextStepAction ?: project.purpose ?: "待项目负责人补充"}", color = MaterialTheme.colorScheme.primary, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
private fun TaskCard(task: CrmTaskRow, onClick: () -> Unit) {
    ContentSection(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Text(task.customerName, modifier = Modifier.weight(1f), fontWeight = FontWeight.Bold)
                StatusTag(taskStatusLabel(task), tone = taskTone(task))
            }
            Text("${task.taskCode} · 截止 ${task.feedbackDueAt?.take(10) ?: "未设置"}", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("问题点：${task.businessIssuePoint ?: "待填写"}", maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text("下一步：${task.latestOwnerNextAction ?: "待补充"}", color = MaterialTheme.colorScheme.primary, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
private fun ProjectDetail(project: ExecutionProject) {
    Column(modifier = Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(project.projectName, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text("${project.projectCode} · ${projectStatusLabel(project)}")
        DetailLine("项目目标", project.purpose ?: "未填写")
        DetailLine("时间", "${project.startDate ?: "-"} 至 ${project.dueDate ?: "-"}")
        DetailLine("任务进度", "${project.taskTotal - project.taskOpen}/${project.taskTotal}")
        DetailLine("待支持 / 阻塞", "${project.taskNeedSupport} / ${project.taskBlocked}")
        DetailLine("下一步", project.nextStepAction ?: "待补充")
    }
}

@Composable
private fun TaskDetail(detail: CrmTaskDetail, canSubmitFollowup: Boolean, onFollowup: (Long) -> Unit) {
    Column(modifier = Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(
            detail.task.customerName,
            modifier = Modifier.testTag("task-detail-title"),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
        )
        Text("${detail.task.taskCode} · ${taskStatusLabel(detail.task)}")
        DetailLine("所属项目", detail.project.projectName)
        DetailLine("项目目标", taskProjectPurposeText(detail.project.purpose))
        DetailLine("执行人", detail.task.executorName ?: "待分配")
        DetailLine("下一步", detail.task.latestOwnerNextAction ?: "待补充")
        if (canSubmitFollowup) {
            LiquidActionButton(onClick = { onFollowup(detail.task.id) }, modifier = Modifier.fillMaxWidth()) { Text("进入跟进填写") }
        }
        Text("关联审批 ${detail.approvals.size}", fontWeight = FontWeight.Bold)
        detail.approvals.take(6).forEach { approval -> Text("${approval.title} · ${approval.status}") }
    }
}

@Composable
private fun DetailLine(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value)
    }
}

internal fun taskProjectPurposeText(value: String?): String = value?.trim().takeUnless { it.isNullOrEmpty() } ?: "未填写"

internal fun projectStatusLabel(project: ExecutionProject): String = when {
    project.overdue -> "已超期"
    project.approvalStatus in setOf("submitted", "under_review") -> "待审批"
    project.status in setOf("closed", "completed") -> "已完成"
    project.status == "cancelled" -> "已取消"
    else -> "进行中"
}

private fun taskStatusLabel(task: CrmTaskRow): String = when {
    task.isClosed -> "已闭环"
    task.isBlocked -> "阻塞"
    task.needSupport -> "待支持"
    task.status == "not_started" -> "未开始"
    else -> "推进中"
}

private fun taskTone(task: CrmTaskRow): StatusTone = when {
    task.isBlocked -> StatusTone.Danger
    task.needSupport -> StatusTone.Warning
    task.isClosed -> StatusTone.Success
    else -> StatusTone.Info
}
