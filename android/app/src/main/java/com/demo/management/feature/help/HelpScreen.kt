package com.demo.management.feature.help

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import com.demo.designsystem.components.ContentSection as Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import com.demo.designsystem.components.LiquidIconButton as IconButton
import androidx.compose.material3.MaterialTheme
import com.demo.designsystem.components.AppScaffold as Scaffold
import androidx.compose.material3.Text
import com.demo.designsystem.components.LiquidTopBar as TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HelpScreen(onClose: () -> Unit) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("帮助中心") },
                navigationIcon = { IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            HelpCard("任务从哪里开始", "进入“任务”，打开任务明细后填写跟进；客户基本资料可以直接保存，经营资料需要提交审批。")
            HelpCard("弱网时怎么处理", "已明确点击提交的跟进、基本资料和待支持会进入同步中心；普通草稿不会自动提交。")
            HelpCard("怎么看审批进度", "工作台进入审批中心，可查看申请内容、当前处理人和处理结果。经营资料审批通过后会同步到主数据。")
            HelpCard("问题仍未解决", "请在“我的 - 问题反馈”提交问题，并保留页面显示的请求编号，便于后台定位。")
        }
    }
}

@Composable
private fun HelpCard(title: String, body: String) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, fontWeight = FontWeight.Bold)
            Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
