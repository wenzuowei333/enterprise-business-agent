package com.demo.management.feature.lead

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import com.demo.designsystem.components.LiquidActionButton as Button
import com.demo.designsystem.components.LiquidBottomActionBar
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.demo.management.feature.customer.ContactOcrButton

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LeadFormScreen(
    ocrEnabled: Boolean,
    features: LeadFormFeatures,
    onClose: () -> Unit,
    onSubmitted: (Long) -> Unit,
    viewModel: LeadFormViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    val form = state.form
    LaunchedEffect(features) { viewModel.configure(features) }
    state.submittedLeadId?.let { submittedLeadId ->
        LaunchedEffect(submittedLeadId) { onSubmitted(submittedLeadId) }
    }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("新建客户线索 ${form.step}/4") },
                navigationIcon = { IconButton(onClick = if (form.step > 1) viewModel::previous else onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } },
            )
        },
        bottomBar = {
            LiquidBottomActionBar {
                Button(
                    onClick = if (form.step == 4) viewModel::submit else viewModel::next,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !state.submitting,
                ) { Text(if (state.submitting) "在线提交中" else if (form.step == 4) "在线提交线索" else "下一步") }
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(leadFormStepTitle(form.step), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            if (state.loading) CircularProgressIndicator()
            if (state.saving) Text("草稿已自动保存", color = MaterialTheme.colorScheme.onSurfaceVariant)
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            state.duplicateMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            state.notice?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
            when (form.step) {
                1 -> LeadContactStep(form, viewModel, ocrEnabled)
                2 -> LeadSourceStep(form, viewModel)
                3 -> LeadIntentStep(form, viewModel, features.productIntentsEnabled)
                else -> LeadPreview(form, features.productIntentsEnabled)
            }
        }
    }
}

@Composable
private fun LeadContactStep(form: LeadFormSnapshot, viewModel: LeadFormViewModel, ocrEnabled: Boolean) {
    if (ocrEnabled) ContactOcrButton(
        currentValues = mapOf("company_name" to form.companyName, "contact_name" to form.contactName, "contact_phone" to form.contactPhone, "region" to form.region),
        onApply = viewModel::applyOcr,
    )
    LeadInput("线索名称", form.leadName) { value -> viewModel.update { it.copy(leadName = value) } }
    LeadInput("公司名称", form.companyName) { value -> viewModel.update { it.copy(companyName = value) } }
    LeadInput("联系人", form.contactName) { value -> viewModel.update { it.copy(contactName = value) } }
    LeadInput("联系电话", form.contactPhone) { value -> viewModel.update { it.copy(contactPhone = value) } }
}

@Composable
private fun LeadSourceStep(form: LeadFormSnapshot, viewModel: LeadFormViewModel) {
    LeadInput("线索来源", form.source) { value -> viewModel.update { it.copy(source = value) } }
    LeadInput("区域", form.region) { value -> viewModel.update { it.copy(region = value) } }
    LeadInput("业务线", form.businessLine) { value -> viewModel.update { it.copy(businessLine = value) } }
    LeadInput("下次跟进时间", form.nextFollowupAt) { value -> viewModel.update { it.copy(nextFollowupAt = value) } }
}

@Composable
private fun LeadIntentStep(form: LeadFormSnapshot, viewModel: LeadFormViewModel, productIntentsEnabled: Boolean) {
    LeadInput("意向摘要", form.intentSummary, lines = 3) { value -> viewModel.update { it.copy(intentSummary = value) } }
    if (productIntentsEnabled) {
        LeadInput("意向产品", form.productName) { value -> viewModel.update { it.copy(productName = value) } }
        LeadInput("产品需求备注", form.productNote, lines = 3) { value -> viewModel.update { it.copy(productNote = value) } }
    }
}

@Composable
private fun LeadPreview(form: LeadFormSnapshot, productIntentsEnabled: Boolean) {
    Text("提交后会立即创建线上线索。", color = MaterialTheme.colorScheme.onSurfaceVariant)
    buildList {
        add("线索名称" to form.leadName)
        add("公司" to form.companyName)
        add("联系人" to form.contactName)
        add("来源" to form.source)
        if (productIntentsEnabled) add("意向产品" to form.productName)
    }.forEach { (label, value) ->
        Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) { Text(label); Text(value.ifBlank { "未填" }) }
    }
}

@Composable
private fun LeadInput(label: String, value: String, lines: Int = 1, onChange: (String) -> Unit) {
    OutlinedTextField(value = value, onValueChange = onChange, label = { Text(label) }, modifier = Modifier.fillMaxWidth(), minLines = lines, maxLines = lines, singleLine = lines == 1)
}

private fun leadFormStepTitle(step: Int) = listOf("", "联系人资料", "来源与跟进", "产品意向", "核对并提交")[step]
