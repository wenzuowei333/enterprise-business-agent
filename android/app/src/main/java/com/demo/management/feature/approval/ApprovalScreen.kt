package com.demo.management.feature.approval

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
import androidx.compose.material3.ExperimentalMaterial3Api
import com.demo.designsystem.components.LiquidFilterChip as FilterChip
import androidx.compose.material3.MaterialTheme
import com.demo.designsystem.components.LiquidBottomSheet as ModalBottomSheet
import com.demo.designsystem.components.LiquidOutlinedButton as OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.demo.management.data.ApprovalDetailEnvelope
import com.demo.management.data.ApprovalSummary

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ApprovalScreen(viewModel: ApprovalViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) viewModel.upload(uri)
    }
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = state.scope == "pending" && state.mode == "to_handle", onClick = { viewModel.setScope("pending", "to_handle") }, label = { Text("待我审批") })
                FilterChip(selected = state.scope == "need_supplement", onClick = { viewModel.setScope("need_supplement", "mine") }, label = { Text("待我补充") })
                FilterChip(selected = state.scope == "active" && state.mode == "mine", onClick = { viewModel.setScope("active", "mine") }, label = { Text("我的提交") })
            }
        }
        item { Text("共 ${state.total} 条", fontWeight = FontWeight.Bold) }
        state.notice?.let { item { Text(it, color = MaterialTheme.colorScheme.primary) } }
        state.error?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
        if (state.loading) item { CircularProgressIndicator() }
        if (!state.loading && state.items.isEmpty()) item { Text("当前没有待处理审批") }
        items(state.items, key = { it.id }) { approval -> ApprovalCard(approval) { viewModel.open(approval.id) } }
        if (state.items.size < state.total) {
            item {
                TextButton(onClick = viewModel::loadMore, modifier = Modifier.fillMaxWidth()) {
                    if (state.loadingMore) CircularProgressIndicator() else Text("加载更多")
                }
            }
        }
    }
    state.selected?.let { detail ->
        ModalBottomSheet(onDismissRequest = viewModel::close) {
            ApprovalDetail(
                detail,
                state.comment,
                state.processing,
                viewModel::updateComment,
                viewModel::act,
                onUpload = { filePicker.launch("*/*") },
            )
        }
    }
}

@Composable
private fun ApprovalCard(approval: ApprovalSummary, onClick: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Text(approval.title, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text(approvalStatus(approval.status), color = MaterialTheme.colorScheme.primary)
            }
            Text(approvalType(approval.approvalType), color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("申请人：${approval.applicantUserLabel ?: "-"} · 处理人：${approval.currentHandlerUserLabel ?: "-"}")
            Text(approval.approvalNo)
        }
    }
}

@Composable
private fun ApprovalDetail(
    detail: ApprovalDetailEnvelope,
    comment: String,
    processing: Boolean,
    onComment: (String) -> Unit,
    onAction: (String) -> Unit,
    onUpload: () -> Unit,
) {
    val approval = detail.approval
    Column(modifier = Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(approval.title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text("${approvalType(approval.approvalType)} · ${approvalStatus(approval.status)}")
        Text("申请人：${approval.applicantUserLabel ?: "-"}")
        Text("处理人：${approval.currentHandlerUserLabel ?: "-"}")
        approval.description?.takeIf { it.isNotBlank() }?.let { Text(it) }
        OutlinedButton(onClick = onUpload, modifier = Modifier.fillMaxWidth()) { Text("上传附件") }
        approval.businessSummary?.entries?.take(8)?.forEach { (key, value) ->
            Text("${businessLabel(key)}：${value ?: "-"}")
        }
        if (detail.events.isNotEmpty()) {
            Text("审批时间线", fontWeight = FontWeight.Bold)
            detail.events.takeLast(6).forEach { event -> Text("${event.createdAt} · ${event.toStatus ?: event.eventType}") }
        }
        if (approval.status in setOf("submitted", "under_review")) {
            OutlinedTextField(value = comment, onValueChange = onComment, label = { Text("审批意见") }, modifier = Modifier.fillMaxWidth(), minLines = 2)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(onClick = { onAction("supplement_request") }, enabled = !processing, modifier = Modifier.weight(1f)) { Text("要求补充") }
                OutlinedButton(onClick = { onAction("reject") }, enabled = !processing, modifier = Modifier.weight(1f)) { Text("驳回") }
                Button(onClick = { onAction("approve") }, enabled = !processing, modifier = Modifier.weight(1f)) { Text("通过") }
            }
        }
    }
}

private fun approvalType(value: String?): String = when (value) {
    "crm_project_create" -> "项目申请"
    "crm_followup_submit" -> "跟进记录"
    "customer_business_profile_update" -> "经营资料更新"
    else -> value ?: "业务审批"
}

private fun approvalStatus(value: String): String = when (value) {
    "draft" -> "草稿"
    "submitted", "under_review" -> "待审批"
    "need_supplement" -> "待补充"
    "completed", "approved" -> "已通过"
    "rejected" -> "已驳回"
    else -> value
}

private fun businessLabel(key: String): String = when (key) {
    "customer_name" -> "客户"
    "project_name" -> "项目"
    "task_code" -> "任务"
    "change_count" -> "变更字段"
    "synced_to_master" -> "已同步主数据"
    else -> key
}
