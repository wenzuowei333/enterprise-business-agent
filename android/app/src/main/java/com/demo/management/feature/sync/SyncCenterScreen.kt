package com.demo.management.feature.sync

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
import androidx.compose.material3.MaterialTheme
import com.demo.designsystem.components.LiquidOutlinedButton as OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.demo.management.data.LocalSyncSummary
import com.demo.management.data.MobileDevice
import com.demo.management.data.local.OutboxOperationEntity
import com.demo.management.data.local.SyncConflictEntity
import java.text.DateFormat
import java.util.Date
import org.json.JSONObject

@Composable
fun SyncCenterScreen(
    onClose: () -> Unit,
    viewModel: SyncCenterViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Column {
                    Text("同步中心", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    Text("查看待提交、冲突和设备会话", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                TextButton(onClick = onClose) { Text("关闭") }
            }
        }
        state.summary?.let { summary -> item { SyncSummaryCard(summary, viewModel::syncNow) } }
        state.notice?.let { item { Text(it, color = MaterialTheme.colorScheme.primary) } }
        state.error?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
        if (state.loading) item { CircularProgressIndicator() }
        if (state.conflicts.isNotEmpty()) {
            item { SectionTitle("待处理冲突", state.conflicts.size) }
            items(state.conflicts, key = { "conflict-${it.operationId}" }) { row ->
                ConflictCard(row, { viewModel.keepServer(row.operationId) }, { viewModel.retryLocal(row.operationId) })
            }
        }
        item { SectionTitle("同步记录", state.operations.size) }
        if (!state.loading && state.operations.isEmpty()) item { Text("暂无待同步或历史操作") }
        items(state.operations, key = { it.operationId }) { row ->
            OperationCard(row, onCancel = { viewModel.cancel(row.operationId) })
        }
        item { SectionTitle("我的设备", state.devices.size) }
        items(state.devices, key = { "device-${it.id}" }) { device ->
            DeviceCard(
                device,
                onRevoke = { viewModel.revokeDevice(device.id) },
                onPreferencesChange = { approval, task, risk ->
                    viewModel.updateNotifications(device.id, approval, task, risk)
                },
            )
        }
    }
}

@Composable
private fun SyncSummaryCard(summary: LocalSyncSummary, onSync: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("同步状态", fontWeight = FontWeight.Bold)
            Text("待提交 ${summary.pending} · 可重试 ${summary.retryable} · 冲突 ${summary.conflicts} · 已拒绝 ${summary.rejected}")
            Text("最近同步：${formatTime(summary.lastSyncedAt)}", color = MaterialTheme.colorScheme.onSurfaceVariant)
            summary.lastError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Button(onClick = onSync, modifier = Modifier.fillMaxWidth()) { Text("立即同步") }
        }
    }
}

@Composable
private fun OperationCard(row: OutboxOperationEntity, onCancel: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Text(actionLabel(row.actionType), fontWeight = FontWeight.Bold)
                Text(statusLabel(row.status), color = statusColor(row.status))
            }
            Text("${row.resourceType ?: "业务记录"} · ${row.resourceId ?: "待生成"}")
            Text("操作编号 ${row.operationId.take(12)}", color = MaterialTheme.colorScheme.onSurfaceVariant)
            row.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (row.status == "pending") OutlinedButton(onClick = onCancel) { Text("取消提交") }
        }
    }
}

@Composable
private fun ConflictCard(row: SyncConflictEntity, keepServer: () -> Unit, retryLocal: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("客户资料存在并发修改", fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.error)
            Text("${row.resourceType ?: "客户"} · ${row.resourceId ?: "-"}")
            Text("服务端和本机修改了相同字段，请选择最终处理方式。")
            conflictLines(row.conflictJson).forEach { line ->
                Text(line, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = keepServer, modifier = Modifier.weight(1f)) { Text("保留服务端") }
                Button(onClick = retryLocal, modifier = Modifier.weight(1f)) { Text("重新提交本地") }
            }
        }
    }
}

private fun conflictLines(value: String): List<String> = runCatching {
    val array = JSONObject(value).optJSONArray("conflicts") ?: return@runCatching emptyList()
    (0 until array.length()).mapNotNull { index ->
        val row = array.optJSONObject(index) ?: return@mapNotNull null
        val field = row.optString("field", "字段")
        val local = row.opt("local_value")?.toString() ?: "空"
        val server = row.opt("server_value")?.toString() ?: "空"
        "$field：本机 $local / 服务端 $server"
    }
}.getOrDefault(emptyList())

@Composable
private fun DeviceCard(
    device: MobileDevice,
    onRevoke: () -> Unit,
    onPreferencesChange: (Boolean, Boolean, Boolean) -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Text(device.deviceName ?: device.deviceModel ?: "Android 设备", fontWeight = FontWeight.Bold)
                Text(if (device.isCurrent) "当前设备" else if (device.revokedAt != null) "已注销" else "正常")
            }
            Text("Android ${device.androidVersion ?: "-"} · App ${device.appVersion ?: "-"}")
            Text("最近使用 ${device.lastUsedAt ?: "-"}", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("最近同步 ${device.lastSyncAt ?: "尚未同步"}", color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (device.isCurrent) {
                val approval = device.notificationPreferences["approval"] != false
                val task = device.notificationPreferences["task"] != false
                val risk = device.notificationPreferences["risk"] != false
                NotificationToggle("审批提醒", approval) { onPreferencesChange(it, task, risk) }
                NotificationToggle("任务与支持", task) { onPreferencesChange(approval, it, risk) }
                NotificationToggle("数据风险", risk) { onPreferencesChange(approval, task, it) }
            }
            if (!device.isCurrent && device.revokedAt == null) {
                OutlinedButton(onClick = onRevoke) { Text("注销此设备") }
            }
        }
    }
}

@Composable
private fun NotificationToggle(label: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
        Text(label)
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}

@Composable private fun SectionTitle(title: String, count: Int) =
    Text("$title（$count）", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)

private fun actionLabel(value: String): String = when (value) {
    "followup.create" -> "跟进记录"
    "support.create" -> "待支持跟进"
    "customer_profile.patch" -> "客户基本资料"
    else -> value
}

private fun statusLabel(value: String): String = when (value) {
    "pending" -> "待提交"
    "processing" -> "提交中"
    "applied" -> "已完成"
    "retryable_error" -> "可重试"
    "conflict" -> "存在冲突"
    "rejected" -> "已拒绝"
    "cancelled" -> "已取消"
    else -> value
}

@Composable private fun statusColor(value: String) = when (value) {
    "applied" -> MaterialTheme.colorScheme.primary
    "conflict", "rejected" -> MaterialTheme.colorScheme.error
    else -> MaterialTheme.colorScheme.tertiary
}

private fun formatTime(value: Long?): String = value?.let { DateFormat.getDateTimeInstance().format(Date(it)) } ?: "尚未同步"
