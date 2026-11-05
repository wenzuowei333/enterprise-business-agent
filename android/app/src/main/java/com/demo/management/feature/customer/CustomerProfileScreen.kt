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
import androidx.compose.material3.OutlinedTextField
import com.demo.designsystem.components.AppScaffold as Scaffold
import androidx.compose.material3.Text
import com.demo.designsystem.components.LiquidTopBar as TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CustomerProfileScreen(code: String, onClose: () -> Unit, ocrEnabled: Boolean = false, viewModel: CustomerProfileViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    LaunchedEffect(code) { viewModel.initialize(code) }
    val form = state.form
    Scaffold(
        topBar = { TopAppBar(title = { Text("编辑客户基本资料") }, navigationIcon = { IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } }) },
        bottomBar = {
            LiquidBottomActionBar {
                Button(onClick = viewModel::save, enabled = !state.saving, modifier = Modifier.fillMaxWidth()) {
                    Text(if (state.saving) "保存中" else "保存并同步主数据")
                }
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            state.notice?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
            if (ocrEnabled) {
                ContactOcrButton(
                    currentValues = customerProfileValues(form).mapValues { it.value.orEmpty() },
                    onApply = { values, _ -> viewModel.applyOcr(values) },
                )
            }
            ProfileField("客户名称", form.customerName) { value -> viewModel.update { it.copy(customerName = value) } }
            ProfileField("客户简称", form.customerShortName) { value -> viewModel.update { it.copy(customerShortName = value) } }
            ProfileField("客户类型", form.customerType) { value -> viewModel.update { it.copy(customerType = value) } }
            ProfileField("所属区域", form.region) { value -> viewModel.update { it.copy(region = value) } }
            ProfileField("联系人", form.contactName) { value -> viewModel.update { it.copy(contactName = value) } }
            ProfileField("联系电话", form.contactPhone) { value -> viewModel.update { it.copy(contactPhone = value) } }
            ProfileField("微信/对接方式", form.contactChannel) { value -> viewModel.update { it.copy(contactChannel = value) } }
            ProfileField("客户群", form.customerGroupName) { value -> viewModel.update { it.copy(customerGroupName = value) } }
            ProfileField("详细地址", form.address, 3) { value -> viewModel.update { it.copy(address = value) } }
        }
    }
}

@Composable
internal fun ProfileField(label: String, value: String, lines: Int = 1, onChange: (String) -> Unit) {
    OutlinedTextField(value = value, onValueChange = onChange, label = { Text(label) }, modifier = Modifier.fillMaxWidth(), minLines = lines, maxLines = lines, singleLine = lines == 1)
}
