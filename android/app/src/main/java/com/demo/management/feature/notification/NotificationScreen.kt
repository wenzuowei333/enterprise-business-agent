package com.demo.management.feature.notification

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import com.demo.designsystem.components.ContentSection as Card
import androidx.compose.material3.CircularProgressIndicator
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
import com.demo.management.data.round3.MobileNotification

@Composable
fun NotificationScreen(
    onClose: () -> Unit,
    onOpen: (MobileNotification) -> Unit,
    smartRemindersEnabled: Boolean = false,
    viewModel: NotificationViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    Column(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("通知中心", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            TextButton(onClick = onClose) { Text("关闭") }
        }
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (state.loading) CircularProgressIndicator()
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (!state.loading && state.items.isEmpty()) item { Text("暂无待处理通知") }
            items(state.items, key = { it.notificationId }) { item ->
                NotificationCard(
                    item,
                    onOpen = { onOpen(item) },
                    onSnooze = if (smartRemindersEnabled) ({ viewModel.snooze(item) }) else null,
                    onHandled = { viewModel.handled(item) },
                )
            }
        }
    }
}

@Composable
private fun NotificationCard(item: MobileNotification, onOpen: () -> Unit, onSnooze: (() -> Unit)?, onHandled: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text(item.title, fontWeight = FontWeight.Bold)
            Text(item.detail ?: "待处理", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(listOfNotNull(item.createdAt, item.dueAt?.let { "截止 $it" }).joinToString(" · "), style = MaterialTheme.typography.labelSmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = onOpen) { Text("查看详情") }
                if (onSnooze != null) TextButton(onClick = onSnooze) { Text("稍后 2 小时") }
                TextButton(onClick = onHandled) { Text("标记已处理") }
            }
        }
    }
}
