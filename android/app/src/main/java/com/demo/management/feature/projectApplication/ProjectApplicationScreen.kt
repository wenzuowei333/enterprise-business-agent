package com.demo.management.feature.projectApplication

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import com.demo.designsystem.components.LiquidActionButton as Button
import com.demo.designsystem.components.LiquidBottomActionBar
import com.demo.designsystem.components.ContentSection as Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import com.demo.designsystem.components.LiquidFilterChip as FilterChip
import androidx.compose.material3.Icon
import com.demo.designsystem.components.LiquidIconButton as IconButton
import androidx.compose.material3.MaterialTheme
import com.demo.designsystem.components.LiquidOutlinedButton as OutlinedButton
import androidx.compose.material3.OutlinedTextField
import com.demo.designsystem.components.AppScaffold as Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import com.demo.designsystem.components.LiquidTopBar as TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.demo.management.data.MobileUser
import com.demo.management.data.MobileUserOption
import com.demo.designsystem.components.LiquidSearchBar

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProjectApplicationScreen(
    applicant: MobileUser,
    prefillCustomerCode: String? = null,
    prefillCustomerName: String? = null,
    onClose: () -> Unit,
    viewModel: ProjectApplicationViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    LaunchedEffect(applicant.id, prefillCustomerCode, prefillCustomerName) {
        viewModel.initialize(applicant, prefillCustomerCode, prefillCustomerName)
    }
    val form = state.form
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("项目申请 ${form.step}/5") },
                navigationIcon = {
                    IconButton(onClick = if (form.step > 1) viewModel::previous else onClose) {
                        Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        bottomBar = {
            LiquidBottomActionBar {
                Column(modifier = Modifier.fillMaxWidth()) {
                    if (form.step == 5) {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                            OutlinedButton(onClick = viewModel::saveDraft, modifier = Modifier.weight(1f), enabled = !state.saving) {
                                Text("保存草稿")
                            }
                            Button(onClick = viewModel::submit, modifier = Modifier.weight(1f), enabled = !state.saving) {
                                Text(if (state.saving) "提交中" else "提交审批")
                            }
                        }
                    } else {
                        Button(onClick = viewModel::next, modifier = Modifier.fillMaxWidth()) { Text("下一步") }
                    }
                }
            }
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Text(stepTitle(form.step), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Text(stepDescription(form.step), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            state.error?.let { error -> item { NoticeCard(error, errorTone = true) } }
            state.notice?.let { notice -> item { NoticeCard(notice) } }
            if (state.loading && state.users.isEmpty()) item { CircularProgressIndicator() }
            when (form.step) {
                1 -> item { BasicProjectStep(state, viewModel) }
                2 -> item { PeopleStep(state, viewModel) }
                3 -> {
                    item { CustomerSearch(state, viewModel) }
                    items(state.customerOptions, key = { it.customerCode }) { customer ->
                        val selected = form.customers.any { it.customerCode == customer.customerCode }
                        Card(modifier = Modifier.fillMaxWidth().clickable { viewModel.toggleCustomer(customer) }) {
                            Row(modifier = Modifier.padding(14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Checkbox(checked = selected, onCheckedChange = { viewModel.toggleCustomer(customer) })
                                Column {
                                    Text(customer.customerName, fontWeight = FontWeight.Bold)
                                    Text(customer.customerCode, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    Text(listOfNotNull(customer.contactName, customer.contactPhone, customer.region).joinToString(" · "))
                                }
                            }
                        }
                    }
                }
                4 -> items(form.customers, key = { it.customerCode }) { customer ->
                    CustomerAssignmentCard(customer, state.users.filter { it.id in form.frontlineUserIds }, viewModel)
                }
                5 -> item { PreviewStep(state) }
            }
            item { Spacer(modifier = Modifier.height(80.dp)) }
        }
    }
}

private fun stepTitle(step: Int) = listOf("", "项目基础信息", "流程人员配置", "选择客户", "分配客户任务", "预览并提交")[step]

private fun stepDescription(step: Int) = listOf(
    "",
    "填写项目目的、时间和闭环要求",
    "配置落地审批、一线执行、细节审批和抄送人员",
    "从客户主数据中搜索并加入项目客户",
    "逐客户确认执行人、问题点、目标和截止时间",
    "确认申请内容后保存草稿或提交审批",
)[step]

@Composable
private fun BasicProjectStep(state: ProjectApplicationUiState, viewModel: ProjectApplicationViewModel) {
    val form = state.form
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Input("项目名称", form.projectName, { value -> viewModel.updateForm { it.copy(projectName = value) } }, required = true)
        Input("项目类型", form.projectType, { value -> viewModel.updateForm { it.copy(projectType = value) } })
        Input("业务线", form.businessLine, { value -> viewModel.updateForm { it.copy(businessLine = value) } })
        Input("项目目的", form.purpose, { value -> viewModel.updateForm { it.copy(purpose = value) } }, lines = 3)
        Input("客户范围说明", form.customerScopeNote, { value -> viewModel.updateForm { it.copy(customerScopeNote = value) } })
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Input("开始日期", form.startDate, { value -> viewModel.updateForm { it.copy(startDate = value) } }, modifier = Modifier.weight(1f))
            Input("截止日期", form.dueDate, { value -> viewModel.updateForm { it.copy(dueDate = value) } }, modifier = Modifier.weight(1f))
        }
        Input("最小动作", form.minimumAction, { value -> viewModel.updateForm { it.copy(minimumAction = value) } }, lines = 2)
        Input("闭环标准", form.closureStandard, { value -> viewModel.updateForm { it.copy(closureStandard = value) } }, lines = 2)
    }
}

@Composable
private fun PeopleStep(state: ProjectApplicationUiState, viewModel: ProjectApplicationViewModel) {
    val form = state.form
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        PersonSection("1. 申请人", "当前账号，只读") {
            Text(state.applicant?.let { "${it.realName} / ${it.username}" } ?: "-")
        }
        PersonSection("2. 项目落地审批人", "单选，默认施总") {
            SingleUserChips(state.users, form.landingApproverUserId) { id -> viewModel.updateForm { it.copy(landingApproverUserId = id) } }
        }
        PersonSection("3. 一线业务员", "多选；仅这些人员可被分配客户任务") {
            MultiUserChips(state.users, form.frontlineUserIds) { viewModel.toggleUser(it) }
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Checkbox(
                    checked = form.allowUnassignedTasks,
                    onCheckedChange = { checked -> viewModel.updateForm { it.copy(allowUnassignedTasks = checked) } },
                )
                Text("稍后分配执行人")
            }
        }
        PersonSection("4. 细节审批人", "单选，处理跟进与经营资料审批") {
            SingleUserChips(state.users, form.ownerUserId) { id -> viewModel.updateForm { it.copy(ownerUserId = id) } }
        }
        PersonSection("5. 项目进展抄送人", "多选，只查看进展，不参与审批") {
            MultiUserChips(state.users, form.progressCcUserIds) { viewModel.toggleUser(it, cc = true) }
        }
    }
}

@Composable
private fun CustomerSearch(state: ProjectApplicationUiState, viewModel: ProjectApplicationViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        LiquidSearchBar(
            value = state.customerQuery,
            onValueChange = viewModel::updateCustomerQuery,
            modifier = Modifier.fillMaxWidth(),
            placeholder = "搜索客户名称、编号、联系人或电话",
            onSearch = viewModel::searchCustomers,
        )
        Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
            Text("已选 ${state.form.customers.size} 个客户", fontWeight = FontWeight.Bold)
            TextButton(onClick = viewModel::searchCustomers) { Text("搜索") }
        }
    }
}

@Composable
private fun CustomerAssignmentCard(
    customer: SelectedProjectCustomer,
    users: List<MobileUserOption>,
    viewModel: ProjectApplicationViewModel,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(customer.customerName, fontWeight = FontWeight.Bold)
            Text(customer.customerCode, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (users.isEmpty()) Text("尚未选择一线业务员", color = MaterialTheme.colorScheme.error)
            else SingleUserChips(users, customer.executorUserId) { viewModel.assignExecutor(customer.customerCode, it) }
            Input("业务问题点", customer.businessIssuePoint, { value ->
                viewModel.updateCustomer(customer.customerCode) { it.copy(businessIssuePoint = value) }
            })
            Input("本轮目标", customer.roundTarget, { value ->
                viewModel.updateCustomer(customer.customerCode) { it.copy(roundTarget = value) }
            })
            Input("反馈截止时间", customer.feedbackDueAt, { value ->
                viewModel.updateCustomer(customer.customerCode) { it.copy(feedbackDueAt = value) }
            })
        }
    }
}

@Composable
private fun PreviewStep(state: ProjectApplicationUiState) {
    val form = state.form
    val userMap = state.users.associateBy { it.id }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(form.projectName, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            PreviewLine("项目类型", form.projectType)
            PreviewLine("项目目的", form.purpose.ifBlank { "-" })
            PreviewLine("落地审批人", userMap[form.landingApproverUserId]?.label ?: "-")
            PreviewLine("细节审批人", userMap[form.ownerUserId]?.label ?: "-")
            PreviewLine("一线业务员", form.frontlineUserIds.mapNotNull { userMap[it]?.realName }.joinToString("、").ifBlank { "稍后分配" })
            PreviewLine("抄送人", form.progressCcUserIds.mapNotNull { userMap[it]?.realName }.joinToString("、").ifBlank { "无" })
            PreviewLine("客户任务", "${form.customers.size} 条")
            form.customers.forEach { row ->
                Text("${row.customerName} · ${userMap[row.executorUserId]?.realName ?: "待分配"}")
            }
        }
    }
}

@Composable
private fun Input(
    label: String,
    value: String,
    onChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    required: Boolean = false,
    lines: Int = 1,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(if (required) "$label *" else label) },
        modifier = modifier.fillMaxWidth(),
        minLines = lines,
        maxLines = lines.coerceAtLeast(1),
        singleLine = lines == 1,
    )
}

@Composable
private fun PersonSection(title: String, detail: String, content: @Composable () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, fontWeight = FontWeight.Bold)
            Text(detail, color = MaterialTheme.colorScheme.onSurfaceVariant)
            content()
        }
    }
}

@Composable
private fun SingleUserChips(users: List<MobileUserOption>, selected: Long?, onSelect: (Long) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
        users.take(4).forEach { user ->
            FilterChip(selected = user.id == selected, onClick = { onSelect(user.id) }, label = { Text(user.realName) })
        }
    }
}

@Composable
private fun MultiUserChips(users: List<MobileUserOption>, selected: List<Long>, onToggle: (Long) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        users.chunked(3).take(4).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { user ->
                    FilterChip(selected = user.id in selected, onClick = { onToggle(user.id) }, label = { Text(user.realName) })
                }
            }
        }
    }
}

@Composable
private fun PreviewLine(label: String, value: String) {
    Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun NoticeCard(message: String, errorTone: Boolean = false) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Text(
            message,
            modifier = Modifier.padding(14.dp),
            color = if (errorTone) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
        )
    }
}
