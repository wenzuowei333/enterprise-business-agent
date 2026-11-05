package com.demo.management.feature.onboarding

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import com.demo.designsystem.components.LiquidDialog as AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp

@Composable
fun RoleOnboardingDialog(role: String, onComplete: () -> Unit) {
    val tasks = onboardingTasks(role)
    AlertDialog(
        onDismissRequest = {},
        title = { Text("开始使用 1.3.0") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("本次升级优先帮助你完成这些工作：")
                tasks.forEachIndexed { index, item -> Text("${index + 1}. $item") }
                Text("AI 仅生成草稿，保存和审批仍需要你亲自确认。")
            }
        },
        confirmButton = { TextButton(onClick = onComplete) { Text("开始工作") } },
    )
}

private fun onboardingTasks(role: String): List<String> = when (role) {
    "admin" -> listOf("查看生产采用情况", "使用 AI 生成可编辑草稿", "处理用户问题反馈")
    "salesperson" -> listOf("查看关联客户和任务", "语音填写跟进", "识别名片并确认资料")
    "boss" -> listOf("处理项目与细节审批", "查看经营风险与项目摘要", "跟踪待支持事项")
    else -> listOf("查看今日待办", "处理任务和审批", "通过问题反馈跟踪使用问题")
}
