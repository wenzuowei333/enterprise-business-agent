package com.demo.designsystem.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

sealed interface StateLayoutState {
    data object Content : StateLayoutState
    data class Loading(val message: String = "正在加载") : StateLayoutState
    data class Empty(val title: String, val detail: String? = null) : StateLayoutState
    data class Error(val message: String, val retryLabel: String = "重试") : StateLayoutState
    data class Offline(val message: String = "当前处于离线模式") : StateLayoutState
    data class Conflict(val message: String) : StateLayoutState
}

@Composable
fun StateLayout(
    state: StateLayoutState,
    modifier: Modifier = Modifier,
    onRetry: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    if (state == StateLayoutState.Content) {
        content()
        return
    }
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            when (state) {
                is StateLayoutState.Loading -> {
                    CircularProgressIndicator()
                    Text(state.message)
                }
                is StateLayoutState.Empty -> {
                    Text(state.title, fontWeight = FontWeight.SemiBold)
                    state.detail?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
                is StateLayoutState.Error -> {
                    Text("暂时无法加载", fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.error)
                    Text(state.message, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    onRetry?.let { LiquidOutlinedButton(onClick = it) { Text(state.retryLabel) } }
                }
                is StateLayoutState.Offline -> {
                    Text("离线模式", fontWeight = FontWeight.SemiBold)
                    Text(state.message, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                is StateLayoutState.Conflict -> {
                    Text("存在待处理冲突", fontWeight = FontWeight.SemiBold)
                    Text(state.message, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                StateLayoutState.Content -> Unit
            }
        }
    }
}
