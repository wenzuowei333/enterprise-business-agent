package com.demo.management.feature.adoption

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
import com.demo.designsystem.components.ContentSection as Card
import androidx.compose.material3.ExperimentalMaterial3Api
import com.demo.designsystem.components.LiquidFilterChip as FilterChip
import androidx.compose.material3.Icon
import com.demo.designsystem.components.LiquidIconButton as IconButton
import androidx.compose.material3.MaterialTheme
import com.demo.designsystem.components.AppScaffold as Scaffold
import androidx.compose.material3.Text
import com.demo.designsystem.components.LiquidTopBar as TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdoptionScreen(onClose: () -> Unit, viewModel: AdoptionViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    val overview = state.overview
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("移动端采用分析") },
                navigationIcon = { IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(7, 30).forEach { days ->
                        FilterChip(selected = state.days == days, onClick = { viewModel.setDays(days) }, label = { Text("近 $days 天") })
                    }
                }
                state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
            if (overview != null) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                        MetricCard("周活跃", overview.weeklyActiveUsers.toString(), "可用账号 ${overview.eligibleUsers}", Modifier.weight(1f))
                        MetricCard("活跃率", String.format(Locale.US, "%.1f%%", overview.weeklyActiveRate), "统计周期 ${overview.days} 天", Modifier.weight(1f))
                    }
                }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                        MetricCard("表单平均耗时", overview.followupFormAvgMs?.let(::formatDuration) ?: "-", "P50 ${overview.followupFormP50Ms?.let(::formatDuration) ?: "-"}", Modifier.weight(1f))
                        MetricCard("反馈平均处理", overview.feedbackResolutionAvgHours?.let { String.format(Locale.US, "%.1f 小时", it) } ?: "-", "已解决反馈", Modifier.weight(1f))
                    }
                }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                        MetricCard("AI 结构化成功率", overview.aiDraftSuccessRate?.let { String.format(Locale.US, "%.1f%%", it) } ?: "-", "仅管理员草稿", Modifier.weight(1f))
                        MetricCard("AI 草稿采用率", overview.aiDraftAdoptionRate?.let { String.format(Locale.US, "%.1f%%", it) } ?: "-", "主动复制草稿", Modifier.weight(1f))
                    }
                }
                item { Text("功能使用", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }
                items(overview.featureUsage.entries.sortedByDescending { it.value }) { item ->
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Row(modifier = Modifier.fillMaxWidth().padding(14.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text(featureLabel(item.key))
                            Text(item.value.toString(), fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun MetricCard(label: String, value: String, detail: String, modifier: Modifier = Modifier) {
    Card(modifier = modifier) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(detail, style = MaterialTheme.typography.labelSmall)
        }
    }
}

private fun formatDuration(value: Long): String = when {
    value < 60_000 -> "${value / 1000} 秒"
    else -> String.format(Locale.US, "%.1f 分钟", value / 60_000.0)
}

private fun featureLabel(key: String): String = when (key) {
    "feedback_submitted" -> "提交问题反馈"
    "voice_input" -> "语音输入"
    "contact_ocr" -> "名片识别"
    "ai_draft_followup" -> "AI 跟进草稿"
    "ai_draft_approval" -> "AI 审批草稿"
    "ai_draft_project" -> "AI 项目摘要"
    else -> key
}
