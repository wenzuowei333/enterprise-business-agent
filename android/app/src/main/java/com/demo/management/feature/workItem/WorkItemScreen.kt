package com.demo.management.feature.workItem

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
import com.demo.designsystem.components.LiquidBottomSheet as ModalBottomSheet
import com.demo.designsystem.components.LiquidOutlinedButton as OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.demo.management.data.WorkItemRow

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkItemScreen(viewModel: WorkItemViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    LazyColumn(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Text("待支持事项 ${state.total}", style = androidx.compose.material3.MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
        state.error?.let { item { Text(it, color = androidx.compose.material3.MaterialTheme.colorScheme.error) } }
        if (state.loading) item { CircularProgressIndicator() }
        if (!state.loading && state.items.isEmpty()) item { Text("当前没有待支持事项") }
        items(state.items, key = { it.id }) { item -> WorkItemCard(item) { viewModel.open(item) } }
    }
    state.selected?.let { item ->
        ModalBottomSheet(onDismissRequest = viewModel::close) {
            Column(modifier = Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(item.customerName ?: item.customerCode ?: "关联客户", fontWeight = FontWeight.Bold)
                Text(item.projectName ?: "未关联项目")
                Text("支持类型：${item.supportType ?: "未填写"}")
                Text("需要支持：${item.supportDetail ?: item.detail ?: "一线未填写支持说明"}")
                if (item.needsNextAction) Text("待补下一步动作")
                OutlinedTextField(value = state.note, onValueChange = viewModel::updateNote, label = { Text("处理说明") }, modifier = Modifier.fillMaxWidth(), minLines = 3)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedButton(onClick = { viewModel.resolve(false) }, enabled = !state.processing, modifier = Modifier.weight(1f)) { Text("处理完成") }
                    Button(onClick = { viewModel.resolve(true) }, enabled = !state.processing, modifier = Modifier.weight(1f)) { Text("关闭事项") }
                }
            }
        }
    }
}

@Composable
private fun WorkItemCard(item: WorkItemRow, onClick: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text("${item.customerName ?: item.customerCode ?: "未知客户"} · ${item.supportType ?: item.title}", fontWeight = FontWeight.Bold)
            Text(item.projectName ?: "未关联项目")
            Text(item.supportDetail ?: item.detail ?: "一线未填写支持说明")
            Text("负责人：${item.assigneeName ?: "待分配"} · ${item.status}")
            if (item.needsNextAction) Text("待补下一步动作")
        }
    }
}
