package com.demo.management.feature.lead

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import com.demo.designsystem.components.LiquidDialog as AlertDialog
import com.demo.designsystem.components.LiquidActionButton as Button
import com.demo.designsystem.components.ContentSection as Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import com.demo.designsystem.components.LiquidIconButton as IconButton
import androidx.compose.material3.MaterialTheme
import com.demo.designsystem.components.LiquidOutlinedButton as OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import com.demo.designsystem.components.LiquidTopBar as TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.demo.management.data.round6.LeadRow

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LeadDetailScreen(
    leadId: Long,
    canQueueFollowup: Boolean,
    canAssign: Boolean,
    canConvert: Boolean,
    canUseProducts: Boolean,
    canOpenProject: Boolean,
    onClose: () -> Unit,
    onOpenProject: (String, String) -> Unit,
    viewModel: LeadDetailViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    var action by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(leadId) { viewModel.load(leadId) }
    com.demo.designsystem.components.AppScaffold(
        topBar = { TopAppBar(title = { Text("客户线索") }, navigationIcon = { IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } }) },
    ) { padding ->
        LazyColumn(modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (state.loading) item { CircularProgressIndicator() }
            state.error?.let { error -> item { Text(error, color = MaterialTheme.colorScheme.error) } }
            state.notice?.let { notice -> item { Text(notice, color = MaterialTheme.colorScheme.primary) } }
            state.lead?.let { lead ->
                item { LeadHeader(lead) }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                        if (canShowQueuedFollowupControl(canQueueFollowup)) OutlinedButton(onClick = { action = "followup" }, modifier = Modifier.weight(1f), enabled = !state.processing) { Text("记录跟进") }
                        if (canAssign) OutlinedButton(onClick = { action = "assign" }, modifier = Modifier.weight(1f), enabled = !state.processing) { Text("分配") }
                    }
                }
                if (canUseProducts) item { OutlinedButton(onClick = { action = "product" }, modifier = Modifier.fillMaxWidth(), enabled = !state.processing) { Text("更新产品意向") } }
                if (canConvert && canRequestLeadConversion(lead.status, lead.currentApprovalStatus)) item { Button(onClick = { action = "convert" }, modifier = Modifier.fillMaxWidth(), enabled = !state.processing) { Text("申请转为客户") } }
                if (canOpenProject && lead.status == "converted" && lead.convertedCustomerCode != null) item {
                    Button(onClick = viewModel::loadProjectPrefill, modifier = Modifier.fillMaxWidth(), enabled = !state.processing) { Text("带入项目申请") }
                }
                state.projectPrefill?.takeIf { canOpenProject }?.let { prefill -> item {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("已选客户：${prefill.customerName}", fontWeight = FontWeight.Bold)
                            Text("进入项目申请后仍需人工填写、保存或提交，不会自动创建项目。")
                            Button(onClick = { onOpenProject(prefill.customerCode, prefill.customerName) }, modifier = Modifier.fillMaxWidth()) { Text("进入项目申请") }
                        }
                    }
                } }
                item { Text("动态", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
                items(leadTimeline(lead, canUseProducts), key = { it }) { line -> Text(line, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) }
            }
        }
    }
    when (action) {
        "followup" -> if (canAcceptLeadDetailAction("followup", canQueueFollowup)) FollowupDialog(onDismiss = { action = null }, onSubmit = { content, nextAt -> viewModel.addFollowup(content, nextAt); action = null })
        "assign" -> AssignDialog(onDismiss = { action = null }, onSubmit = { userId, note -> viewModel.assign(userId, note); action = null })
        "product" -> ProductIntentDialog(onDismiss = { action = null }, onSubmit = { name, note -> viewModel.replaceProductIntent(name, note, canUseProducts); action = null })
        "convert" -> ConvertDialog(onDismiss = { action = null }, onSubmit = { note -> viewModel.requestConversion(note); action = null })
    }
}

internal fun canShowQueuedFollowupControl(canQueueFollowup: Boolean): Boolean = canQueueFollowup

internal fun canAcceptLeadDetailAction(action: String, canQueueFollowup: Boolean): Boolean =
    action != "followup" || canQueueFollowup

@Composable
private fun LeadHeader(lead: LeadRow) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(lead.leadName, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(leadStatusLabel(lead.status), color = MaterialTheme.colorScheme.primary)
            Detail("公司", lead.companyName)
            Detail("联系人", listOfNotNull(lead.contactName, lead.contactPhone).joinToString(" · "))
            Detail("来源", lead.source)
            Detail("下次跟进", lead.nextFollowupAt)
        }
    }
}

@Composable
private fun Detail(label: String, value: String?) {
    Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value?.ifBlank { "未填" } ?: "未填")
    }
}

private fun leadTimeline(lead: LeadRow, showProductIntents: Boolean): List<String> = buildList {
    lead.assignments.forEach { add("分配 · ${it.createdAt ?: "待同步"} · ${it.note ?: "已更新负责人"}") }
    lead.followups.forEach { add("跟进 · ${it.createdAt ?: "待同步"} · ${it.content}") }
    if (showProductIntents) lead.productIntents.forEach { add("产品意向 · ${it.productName}${it.note?.let { note -> " · $note" }.orEmpty()}") }
    lead.convertedAt?.let { add("已转为客户 · $it") }
    if (isEmpty()) add("暂无动态")
}

@Composable
private fun FollowupDialog(onDismiss: () -> Unit, onSubmit: (String, String) -> Unit) {
    var content by remember { mutableStateOf("") }; var nextAt by remember { mutableStateOf("") }
    LeadDialog("记录跟进", onDismiss, { onSubmit(content, nextAt) }) {
        DialogInput("跟进内容", content, { content = it }, 3); DialogInput("下次跟进时间", nextAt, { nextAt = it })
    }
}

@Composable
private fun AssignDialog(onDismiss: () -> Unit, onSubmit: (Long?, String) -> Unit) {
    var userId by remember { mutableStateOf("") }; var note by remember { mutableStateOf("") }
    LeadDialog("分配负责人", onDismiss, { onSubmit(userId.toLongOrNull(), note) }) {
        DialogInput("负责人用户 ID（留空取消分配）", userId, { userId = it }); DialogInput("备注", note, { note = it })
    }
}

@Composable
private fun ProductIntentDialog(onDismiss: () -> Unit, onSubmit: (String, String) -> Unit) {
    var name by remember { mutableStateOf("") }; var note by remember { mutableStateOf("") }
    LeadDialog("更新产品意向", onDismiss, { if (name.isNotBlank()) onSubmit(name, note) }) {
        DialogInput("产品名称", name, { name = it }); DialogInput("需求备注", note, { note = it }, 3)
    }
}

@Composable
private fun ConvertDialog(onDismiss: () -> Unit, onSubmit: (String) -> Unit) {
    var note by remember { mutableStateOf("") }
    LeadDialog("申请转为客户", onDismiss, { onSubmit(note) }) { DialogInput("申请说明", note, { note = it }, 3) }
}

@Composable
private fun LeadDialog(title: String, onDismiss: () -> Unit, onConfirm: () -> Unit, content: @Composable () -> Unit) {
    AlertDialog(onDismissRequest = onDismiss, title = { Text(title) }, text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) { content() } }, confirmButton = { Button(onClick = onConfirm) { Text("确认") } }, dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } })
}

@Composable
private fun DialogInput(label: String, value: String, onChange: (String) -> Unit, lines: Int = 1) {
    OutlinedTextField(value = value, onValueChange = onChange, label = { Text(label) }, minLines = lines, maxLines = lines, singleLine = lines == 1)
}
