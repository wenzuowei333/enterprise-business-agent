package com.demo.management.feature.feedback

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.AddPhotoAlternate
import com.demo.designsystem.components.LiquidActionButton as Button
import com.demo.designsystem.components.ContentSection as Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import com.demo.designsystem.components.LiquidFilterChip as FilterChip
import androidx.compose.material3.Icon
import com.demo.designsystem.components.LiquidIconButton as IconButton
import androidx.compose.material3.MaterialTheme
import com.demo.designsystem.components.LiquidOutlinedButton as OutlinedButton
import androidx.compose.material3.OutlinedTextField
import com.demo.designsystem.components.AppScaffold as Scaffold
import androidx.compose.material3.Text
import com.demo.designsystem.components.LiquidTopBar as TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.demo.management.data.round5.FeedbackRow

private val categories = listOf(
    "bug" to "功能问题",
    "experience" to "体验问题",
    "request" to "功能建议",
    "other" to "其他",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeedbackScreen(sourceRoute: String?, onClose: () -> Unit, viewModel: FeedbackViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent(), viewModel::selectScreenshot)
    LaunchedEffect(sourceRoute) { viewModel.initialize(sourceRoute) }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("问题反馈") },
                navigationIcon = { IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Text("反馈内容", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    items(categories) { (code, label) ->
                        FilterChip(
                            selected = state.category == code,
                            onClick = { viewModel.updateCategory(code) },
                            label = { Text(label) },
                        )
                    }
                }
                OutlinedTextField(
                    value = state.description,
                    onValueChange = viewModel::updateDescription,
                    label = { Text("请描述问题或建议") },
                    supportingText = { Text("请勿填写客户电话、地址或其他敏感业务内容") },
                    minLines = 4,
                    maxLines = 8,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            item {
                OutlinedButton(onClick = { picker.launch("image/*") }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Outlined.AddPhotoAlternate, contentDescription = null)
                    Text(if (state.screenshot == null) " 选择截图（可选）" else " 更换截图")
                }
                state.screenshot?.let { uri ->
                    AsyncImage(
                        model = uri,
                        contentDescription = "反馈截图预览",
                        modifier = Modifier.fillMaxWidth().height(180.dp).padding(top = 8.dp),
                    )
                    Row(modifier = Modifier.fillMaxWidth()) {
                        Checkbox(checked = state.screenshotConfirmed, onCheckedChange = viewModel::confirmScreenshot)
                        Text("我已检查截图，确认其中不含不应上传的敏感信息", modifier = Modifier.padding(top = 12.dp))
                    }
                }
                state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                state.notice?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
                Button(
                    onClick = viewModel::submit,
                    enabled = !state.sending && (state.screenshot == null || state.screenshotConfirmed),
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(if (state.sending) "提交中" else "提交反馈") }
            }
            item { Text("我的反馈", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
            if (!state.loading && state.items.isEmpty()) item { Text("暂无反馈记录") }
            items(state.items, key = { it.id }) { FeedbackCard(it) }
        }
    }
}

@Composable
private fun FeedbackCard(item: FeedbackRow) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(feedbackCategory(item.category), fontWeight = FontWeight.Bold)
                Text(feedbackStatus(item.status), color = MaterialTheme.colorScheme.primary)
            }
            Text(item.description, maxLines = 3)
            item.resolution?.takeIf(String::isNotBlank)?.let { Text("处理结果：$it", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Text(item.createdAt, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

private fun feedbackStatus(status: String): String = when (status) {
    "processing" -> "处理中"
    "resolved" -> "已解决"
    "closed" -> "已关闭"
    else -> "待处理"
}

private fun feedbackCategory(category: String): String = when (category) {
    "bug" -> "功能问题"
    "experience" -> "体验问题"
    "request" -> "功能建议"
    else -> "其他"
}
