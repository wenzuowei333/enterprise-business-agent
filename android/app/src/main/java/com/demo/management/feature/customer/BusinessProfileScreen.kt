package com.demo.management.feature.customer

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import com.demo.designsystem.components.LiquidActionButton as Button
import com.demo.designsystem.components.LiquidBottomActionBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import com.demo.designsystem.components.LiquidIconButton as IconButton
import androidx.compose.material3.MaterialTheme
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BusinessProfileScreen(code: String, name: String, onClose: () -> Unit, viewModel: BusinessProfileViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    LaunchedEffect(code) { viewModel.initialize(code, name) }
    val form = state.form
    Scaffold(
        topBar = { TopAppBar(title = { Text("填写经营资料") }, navigationIcon = { IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } }) },
        bottomBar = {
            LiquidBottomActionBar {
                Button(onClick = viewModel::submit, enabled = !state.saving, modifier = Modifier.fillMaxWidth()) {
                    Text(if (state.saving) "保存中" else "保存经营资料")
                }
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            state.notice?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
            ProfileField("经营客户类型", form.customerType) { value -> viewModel.update { it.copy(customerType = value) } }
            ProfileField("经营状态", form.businessStatus) { value -> viewModel.update { it.copy(businessStatus = value) } }
            ProfileField("经营状态说明", form.statusNote, 3) { value -> viewModel.update { it.copy(statusNote = value) } }
            ProfileField("本次更新说明", form.updateNote, 3) { value -> viewModel.update { it.copy(updateNote = value) } }
            Text("本次拜访推荐产品", fontWeight = FontWeight.Bold)
            ProfileField("产品名称", form.recommendedProductName) { value -> viewModel.update { it.copy(recommendedProductName = value) } }
            ProfileField("规格", form.recommendedSpec) { value -> viewModel.update { it.copy(recommendedSpec = value) } }
            ProfileField("推荐报价", form.recommendedQuote) { value -> viewModel.update { it.copy(recommendedQuote = value) } }
            ProfileField("推荐原因", form.recommendReason, 2) { value -> viewModel.update { it.copy(recommendReason = value) } }
            ProfileField("客户反馈", form.customerFeedback, 2) { value -> viewModel.update { it.copy(customerFeedback = value) } }
            ProfileField("后续动作", form.nextAction, 2) { value -> viewModel.update { it.copy(nextAction = value) } }
        }
    }
}
