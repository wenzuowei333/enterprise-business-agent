package com.demo.management.feature.profile

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import com.demo.designsystem.components.LiquidDialog as AlertDialog
import com.demo.designsystem.components.LiquidActionButton as Button
import com.demo.designsystem.components.ContentSection as Card
import androidx.compose.material3.MaterialTheme
import com.demo.designsystem.components.LiquidOutlinedButton as OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.demo.management.BuildConfig
import com.demo.management.core.update.UpdateDecision
import com.demo.management.data.BootstrapPayload
import com.demo.management.data.LocalSyncSummary

@Composable
fun ProfileScreen(
    bootstrap: BootstrapPayload?,
    localDraftCount: Int,
    syncSummary: LocalSyncSummary?,
    onRefreshDrafts: () -> Unit,
    onClearDrafts: () -> Unit,
    onSync: () -> Unit,
    onRefreshSync: () -> Unit,
    onOpenSyncCenter: () -> Unit,
    onStartUpdate: () -> Unit,
    updateDecision: UpdateDecision,
    canOpenHelp: Boolean,
    canOpenFeedback: Boolean,
    canOpenAiDrafts: Boolean,
    canOpenAdoption: Boolean,
    onOpenAppearance: () -> Unit,
    onOpenHelp: () -> Unit,
    onOpenFeedback: () -> Unit,
    onOpenAiDrafts: () -> Unit,
    onOpenAdoption: () -> Unit,
    onLogout: () -> Unit,
) {
    var confirmClear by remember { mutableStateOf(false) }
    Text("我的", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
    bootstrap?.user?.let { user ->
        Spacer(modifier = Modifier.height(12.dp))
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(user.realName.ifBlank { user.username }, fontWeight = FontWeight.Bold)
                Text(user.username, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("当前版本 ${BuildConfig.VERSION_NAME}", color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (updateDecision != UpdateDecision.None) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Button(onClick = onStartUpdate) { Text("更新到 ${bootstrap.app.latestVersion}") }
                }
            }
        }
    }
    Spacer(modifier = Modifier.height(12.dp))
    OutlinedButton(onClick = onOpenAppearance, modifier = Modifier.fillMaxWidth()) { Text("外观") }
    Spacer(modifier = Modifier.height(12.dp))
    if (canOpenHelp || canOpenFeedback || canOpenAiDrafts || canOpenAdoption) {
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("支持与改进", fontWeight = FontWeight.Bold)
                if (canOpenHelp || canOpenFeedback) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                        if (canOpenHelp) OutlinedButton(onClick = onOpenHelp, modifier = Modifier.weight(1f)) { Text("帮助中心") }
                        if (canOpenFeedback) OutlinedButton(onClick = onOpenFeedback, modifier = Modifier.weight(1f)) { Text("问题反馈") }
                    }
                }
                if (canOpenAiDrafts || canOpenAdoption) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                        if (canOpenAiDrafts) OutlinedButton(onClick = onOpenAiDrafts, modifier = Modifier.weight(1f)) { Text("AI 草稿") }
                        if (canOpenAdoption) OutlinedButton(onClick = onOpenAdoption, modifier = Modifier.weight(1f)) { Text("采用分析") }
                    }
                }
            }
        }
        Spacer(modifier = Modifier.height(12.dp))
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("同步与离线", fontWeight = FontWeight.Bold)
            Text(
                "待提交 ${syncSummary?.pending ?: 0} · 可重试 ${syncSummary?.retryable ?: 0} · 冲突 ${syncSummary?.conflicts ?: 0}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { onSync(); onRefreshSync() }, modifier = Modifier.weight(1f)) { Text("立即同步") }
                OutlinedButton(onClick = onOpenSyncCenter, modifier = Modifier.weight(1f)) { Text("同步中心") }
            }
        }
    }
    Spacer(modifier = Modifier.height(12.dp))
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("本地草稿", fontWeight = FontWeight.Bold)
            Text("共 $localDraftCount 份", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(modifier = Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = onRefreshDrafts) { Text("刷新") }
                OutlinedButton(onClick = { confirmClear = true }, enabled = localDraftCount > 0) { Text("清除草稿") }
            }
        }
    }
    Spacer(modifier = Modifier.height(16.dp))
    Button(onClick = onLogout, modifier = Modifier.fillMaxWidth()) { Text("退出登录") }
    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            title = { Text("清除本地草稿") },
            text = { Text("未提交的项目、跟进和资料草稿将被删除，此操作无法撤销。") },
            confirmButton = {
                TextButton(onClick = { confirmClear = false; onClearDrafts() }) { Text("确认清除") }
            },
            dismissButton = { TextButton(onClick = { confirmClear = false }) { Text("取消") } },
        )
    }
}
