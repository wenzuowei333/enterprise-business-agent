package com.demo.management.feature.assistant

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import com.demo.designsystem.components.LiquidActionButton as Button
import com.demo.designsystem.components.ContentSection as Card
import androidx.compose.material3.ExperimentalMaterial3Api
import com.demo.designsystem.components.LiquidFilterChip as FilterChip
import androidx.compose.material3.Icon
import com.demo.designsystem.components.LiquidIconButton as IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import com.demo.designsystem.components.AppScaffold as Scaffold
import androidx.compose.material3.Text
import com.demo.designsystem.components.LiquidTopBar as TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.hilt.navigation.compose.hiltViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AiDraftScreen(onClose: () -> Unit, viewModel: AiDraftViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    val clipboard = LocalClipboardManager.current
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("AI 草稿") },
                navigationIcon = { IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("AI 只生成草稿，不会保存、提交或执行审批。", color = MaterialTheme.colorScheme.primary)
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                items(AiDraftType.entries) { type ->
                    FilterChip(selected = state.type == type, onClick = { viewModel.selectType(type) }, label = { Text(type.label) })
                }
            }
            OutlinedTextField(
                value = state.resourceId,
                onValueChange = viewModel::updateResourceId,
                label = { Text(resourceLabel(state.type)) },
                supportingText = { Text("可选；只会读取当前账号有权限的业务上下文") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            OutlinedTextField(
                value = state.text,
                onValueChange = viewModel::updateText,
                label = { Text("需要整理的原始文字") },
                minLines = 5,
                maxLines = 12,
                modifier = Modifier.fillMaxWidth(),
            )
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Button(onClick = viewModel::generate, enabled = !state.loading, modifier = Modifier.fillMaxWidth()) {
                Text(if (state.loading) "生成中" else "生成可编辑草稿")
            }
            state.result?.let { result ->
                Text("草稿结果", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Button(
                    onClick = {
                        clipboard.setText(AnnotatedString(result.fields.entries.joinToString("\n") { "${fieldLabel(it.key)}：${renderDraftValue(it.value)}" }))
                        viewModel.markAdopted()
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("复制草稿内容") }
                result.fields.forEach { (key, value) ->
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(fieldLabel(key), fontWeight = FontWeight.Bold)
                            Text(renderDraftValue(value))
                        }
                    }
                }
                result.warnings.forEach { Text("风险提示：$it", color = MaterialTheme.colorScheme.error) }
                if (result.sourceRefs.isNotEmpty()) Text("引用来源：${result.sourceRefs.joinToString("、")}", style = MaterialTheme.typography.labelSmall)
                Text("生成时间：${result.generatedAt}", style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

private fun resourceLabel(type: AiDraftType): String = when (type) {
    AiDraftType.FOLLOWUP -> "任务 ID"
    AiDraftType.APPROVAL -> "审批 ID"
    AiDraftType.PROJECT -> "项目 ID"
}

private fun fieldLabel(key: String): String = when (key) {
    "customer_feedback" -> "客户反馈"
    "current_need" -> "当前需求"
    "blocker_reason" -> "卡点"
    "next_action" -> "下一步动作"
    "opinion" -> "审批意见"
    "summary" -> "项目摘要"
    else -> key.replace('_', ' ')
}

private fun renderDraftValue(value: Any?): String = when (value) {
    is List<*> -> value.joinToString("\n") { "• ${it.orEmptyLabel()}" }
    is Map<*, *> -> value.entries.joinToString("\n") { "${it.key}: ${it.value.orEmptyLabel()}" }
    else -> value.orEmptyLabel()
}

private fun Any?.orEmptyLabel(): String = this?.toString()?.takeIf(String::isNotBlank) ?: "-"
