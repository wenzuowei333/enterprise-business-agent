package com.demo.management.feature.followup

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
import androidx.compose.material3.Checkbox
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
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.hilt.navigation.compose.hiltViewModel
import com.demo.management.core.voice.VoiceInputButton
import com.demo.management.core.voice.appendRecognizedText

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FollowupScreen(taskId: Long, onClose: () -> Unit, voiceEnabled: Boolean = false, viewModel: FollowupViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()
    var voiceError by remember { mutableStateOf<String?>(null) }
    val attachmentPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { values ->
        viewModel.addAttachments(values)
    }
    LaunchedEffect(taskId) { viewModel.initialize(taskId) }
    val form = state.form
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("填写跟进") },
                navigationIcon = { IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } },
            )
        },
        bottomBar = {
            LiquidBottomActionBar {
                Button(onClick = viewModel::submit, enabled = !state.saving, modifier = Modifier.fillMaxWidth()) {
                    Text(if (state.saving) "提交中" else "提交细节审批")
                }
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            state.task?.let { Text("${it.task.customerName} · ${it.project.projectName}") }
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            voiceError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            state.notice?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
            Field("跟进日期", form.followupDate) { value -> viewModel.update { it.copy(followupDate = value) } }
            Field("跟进方式", form.method) { value -> viewModel.update { it.copy(method = value) } }
            Field("一线动作", form.frontlineAction, 2) { value -> viewModel.update { it.copy(frontlineAction = value) } }
            Field("客户反馈 *", form.customerFeedback, 3, voiceEnabled, { recognized ->
                voiceError = null
                viewModel.recordVoiceInput()
                viewModel.update { it.copy(customerFeedback = appendRecognizedText(it.customerFeedback, recognized)) }
            }, { voiceError = it }) { value -> viewModel.update { it.copy(customerFeedback = value) } }
            Field("当前需求", form.currentNeed, 2, voiceEnabled, { recognized ->
                voiceError = null
                viewModel.recordVoiceInput()
                viewModel.update { it.copy(currentNeed = appendRecognizedText(it.currentNeed, recognized)) }
            }, { voiceError = it }) { value -> viewModel.update { it.copy(currentNeed = value) } }
            Field("卡点原因", form.blockerReason) { value -> viewModel.update { it.copy(blockerReason = value) } }
            Field("卡点说明", form.blockerNote, 2, voiceEnabled, { recognized ->
                voiceError = null
                viewModel.recordVoiceInput()
                viewModel.update { it.copy(blockerNote = appendRecognizedText(it.blockerNote, recognized)) }
            }, { voiceError = it }) { value -> viewModel.update { it.copy(blockerNote = value) } }
            Field("下一步动作 *", form.nextAction, 2, voiceEnabled, { recognized ->
                voiceError = null
                viewModel.recordVoiceInput()
                viewModel.update { it.copy(nextAction = appendRecognizedText(it.nextAction, recognized)) }
            }, { voiceError = it }) { value -> viewModel.update { it.copy(nextAction = value) } }
            Field("下次跟进时间", form.nextFollowupAt) { value -> viewModel.update { it.copy(nextFollowupAt = value) } }
            Check("完成最小动作", form.minimumActionDone) { checked -> viewModel.update { it.copy(minimumActionDone = checked) } }
            Check("完成客户基本资料更新", form.customerProfileUpdated) { checked -> viewModel.update { it.copy(customerProfileUpdated = checked) } }
            Check("完成客户经营资料更新", form.businessProfileUpdated) { checked -> viewModel.update { it.copy(businessProfileUpdated = checked) } }
            Check("需要支持", form.needSupport) { checked -> viewModel.update { it.copy(needSupport = checked) } }
            if (form.needSupport) Field("支持类型", form.needType) { value -> viewModel.update { it.copy(needType = value) } }
            Button(onClick = { attachmentPicker.launch(arrayOf("image/*", "application/pdf")) }, modifier = Modifier.fillMaxWidth()) {
                Text(if (state.attachments.isEmpty()) "添加图片或附件" else "已选择 ${state.attachments.size} 个附件")
            }
            Check("建议任务闭环", form.isClosed) { checked -> viewModel.update { it.copy(isClosed = checked) } }
        }
    }
}

@Composable
private fun Field(
    label: String,
    value: String,
    lines: Int = 1,
    voiceEnabled: Boolean = false,
    onVoice: (String) -> Unit = {},
    onVoiceError: (String) -> Unit = {},
    onChange: (String) -> Unit,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        modifier = Modifier.fillMaxWidth(),
        minLines = lines,
        maxLines = lines,
        singleLine = lines == 1,
        trailingIcon = if (voiceEnabled) ({ VoiceInputButton(onVoice, onVoiceError) }) else null,
    )
}

@Composable
private fun Check(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Checkbox(checked = checked, onCheckedChange = onChange)
        Text(label, modifier = Modifier.padding(top = 12.dp))
    }
}
