package com.demo.management

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToIndex
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.demo.designsystem.theme.LiquidTheme
import com.demo.management.data.MobileExceptionCase
import com.demo.management.data.MobileExceptionDetail
import com.demo.management.data.MobileExceptionSummary
import com.demo.management.data.MobileExceptionCapabilities
import com.demo.management.data.MobileDiagnosisJob
import com.demo.management.data.MobileAiActionProposal
import com.demo.management.data.MobileAiActionValidation
import com.demo.management.feature.exception.ExceptionCenterContent
import com.demo.management.feature.exception.ExceptionCenterUiState
import org.junit.Rule
import org.junit.Test

class ExceptionCenterComposeTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun exceptionCenterRendersMetricsCaseAndOnlineOnlyEvidence() {
        composeRule.setContent {
            LiquidTheme {
                ExceptionCenterContent(
                    state = ExceptionCenterUiState(
                        summary = MobileExceptionSummary(open = 2, actionRequired = 1, blocked = 1, overdue = 2),
                        items = listOf(sampleCase()),
                        total = 1,
                        selected = sampleDetail(),
                    ),
                    onView = {},
                    onQueryChange = {},
                    onSearch = {},
                    onDomain = {},
                    onSeverity = {},
                    onStatus = {},
                    onAssignment = {},
                    onLoadMore = {},
                    onOpen = {},
                    onClose = {},
                    onDiagnose = {},
                    onOpenAction = {},
                    onCloseAction = {},
                    onValidateAction = {},
                    onExecuteAction = {},
                )
            }
        }

        composeRule.onNodeWithText("待处置").assertIsDisplayed()
        composeRule.onNodeWithTag("exception-detail-title").assertIsDisplayed()
        composeRule.onNodeWithTag("exception-detail-list").performScrollToIndex(7)
        composeRule.onNodeWithText("当前证据").assertIsDisplayed()
        composeRule.onNodeWithTag("exception-detail-list").performScrollToIndex(8)
        composeRule.onNodeWithText("账实差异 8 件").assertIsDisplayed()
        composeRule.onNodeWithTag("exception-detail-list").performScrollToIndex(9)
        composeRule.onNodeWithText("异常详情仅在线读取，不会保存到本机。").assertIsDisplayed()
    }

    @Test
    fun diagnosisProgressAndControlledActionRequireExplicitConfirmation() {
        val proposal = MobileAiActionProposal(
            id = 3,
            proposalNo = "AI-EXC-PROP-3",
            domain = "inventory",
            actionType = "rerun_inventory_check",
            resourceType = "exception_case",
            resourceId = "EX-20260831-001",
            status = "validated",
            reviewStatus = "pending",
            riskLevel = "high",
            impact = mapOf("batch_id" to 12),
            executable = true,
            createdAt = "2026-08-31T08:00:00Z",
            updatedAt = "2026-08-31T08:01:00Z",
        )
        var state by mutableStateOf(
            ExceptionCenterUiState(
                view = "actions",
                capabilities = MobileExceptionCapabilities(diagnose = true, executeAction = true),
                selected = sampleDetail().copy(capabilities = MobileExceptionCapabilities(diagnose = true)),
                diagnosisJob = MobileDiagnosisJob(
                    id = 8,
                    jobNo = "JOB-8",
                    caseNo = "EX-20260831-001",
                    evidenceVersion = "ev-1",
                    triggerType = "manual",
                    status = "processing",
                    createdAt = "2026-08-31T08:02:00Z",
                ),
                actions = listOf(proposal),
                actionTotal = 1,
            )
        )
        composeRule.setContent {
            LiquidTheme {
                ExceptionCenterContent(
                    state = state,
                    onView = {},
                    onQueryChange = {},
                    onSearch = {},
                    onDomain = {},
                    onSeverity = {},
                    onStatus = {},
                    onAssignment = {},
                    onLoadMore = {},
                    onOpen = {},
                    onClose = {},
                    onDiagnose = {},
                    onOpenAction = {},
                    onCloseAction = {},
                    onValidateAction = {},
                    onExecuteAction = {},
                )
            }
        }

        composeRule.onNodeWithTag("exception-detail-list").performScrollToIndex(8)
        composeRule.onNodeWithTag("exception-diagnosis-progress").assertIsDisplayed()
        composeRule.runOnIdle {
            state = state.copy(
                selected = null,
                diagnosisJob = null,
                selectedAction = proposal,
                actionValidation = MobileAiActionValidation(proposal, validationToken = "temporary-token-for-test"),
            )
        }
        composeRule.onNodeWithText("确认影响并执行").performClick()
        composeRule.onNodeWithText("确认执行受控动作").assertIsDisplayed()
        composeRule.onNodeWithText("人工确认执行").assertIsDisplayed()
    }

    @Test
    fun diagnosisAndControlledActionsAreHiddenWithoutCapabilities() {
        composeRule.setContent {
            LiquidTheme {
                ExceptionCenterContent(
                    state = ExceptionCenterUiState(
                        capabilities = MobileExceptionCapabilities(),
                        selected = sampleDetail().copy(
                            capabilities = MobileExceptionCapabilities(),
                            diagnosisSupported = true,
                        ),
                    ),
                    onView = {},
                    onQueryChange = {},
                    onSearch = {},
                    onDomain = {},
                    onSeverity = {},
                    onStatus = {},
                    onAssignment = {},
                    onLoadMore = {},
                    onOpen = {},
                    onClose = {},
                    onDiagnose = {},
                    onOpenAction = {},
                    onCloseAction = {},
                    onValidateAction = {},
                    onExecuteAction = {},
                )
            }
        }

        composeRule.onNodeWithText("受控动作").assertDoesNotExist()
        composeRule.onNodeWithText("发起 AI 诊断").assertDoesNotExist()
    }

    private fun sampleCase() = MobileExceptionCase(
        id = 1,
        caseNo = "EX-20260831-001",
        domain = "inventory",
        diagnosisSupported = true,
        ruleCode = "inventory_gap",
        title = "库存数量不一致",
        severity = "high",
        status = "open",
        sourceType = "inventory_check",
        evidenceVersion = "ev-1",
        reason = "系统库存与盘点数量不一致",
        resourceName = "测试商品",
        lastSeenAt = "2026-08-31T08:00:00Z",
    )

    private fun sampleDetail() = MobileExceptionDetail(
        id = 1,
        caseNo = "EX-20260831-001",
        domain = "inventory",
        diagnosisSupported = true,
        ruleCode = "inventory_gap",
        title = "库存数量不一致",
        severity = "high",
        status = "open",
        evidenceVersion = "ev-1",
        reason = "系统库存与盘点数量不一致",
        resourceName = "测试商品",
        lastSeenAt = "2026-08-31T08:00:00Z",
        evidence = mapOf("summary" to "账实差异 8 件"),
    )
}
