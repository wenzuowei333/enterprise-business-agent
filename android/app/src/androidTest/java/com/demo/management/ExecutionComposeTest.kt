package com.demo.management

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import com.demo.designsystem.theme.LiquidTheme
import com.demo.management.data.CrmProjectSummary
import com.demo.management.data.CrmTaskDetail
import com.demo.management.data.CrmTaskRow
import com.demo.management.data.ExecutionCapabilities
import com.demo.management.data.ExecutionPayload
import com.demo.management.data.ExecutionProject
import com.demo.management.data.ExecutionProjectPage
import com.demo.management.data.ExecutionSummary
import com.demo.management.data.ExecutionTaskPage
import com.demo.management.feature.task.TaskContent
import com.demo.management.feature.task.TaskUiState
import org.junit.Rule
import org.junit.Test

class ExecutionComposeTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun projectExecutionAndMyWorkRenderTheirPrimaryActions() {
        var state = sampleState()
        composeRule.setContent {
            LiquidTheme {
                TaskContent(
                    state = state,
                    onSetView = { state = state.copy(view = it) },
                    onQueryChange = {},
                    onProjectFilter = {},
                    onTaskFilter = {},
                    onRefresh = {},
                    onOpenTask = {},
                    onCloseTask = {},
                    onFollowup = {},
                    onCreateProject = {},
                )
            }
        }

        composeRule.onNodeWithText("项目执行").assertIsDisplayed()
        composeRule.onNodeWithText("申请新项目").assertIsDisplayed()
        composeRule.onNodeWithText("城配扩容项目").assertIsDisplayed().performClick()
        composeRule.onNodeWithText("项目目标").assertIsDisplayed()
    }

    @Test
    fun projectWorkspaceShowsFulfillmentEntryWhenEnabled() {
        composeRule.setContent {
            LiquidTheme {
                TaskContent(
                    state = sampleState(),
                    onSetView = {},
                    onQueryChange = {},
                    onProjectFilter = {},
                    onTaskFilter = {},
                    onRefresh = {},
                    onOpenTask = {},
                    onCloseTask = {},
                    onFollowup = {},
                    onCreateProject = {},
                    canOpenDeliveries = true,
                    onOpenDeliveries = {},
                )
            }
        }

        composeRule.onNodeWithText("配送履约").assertIsDisplayed()
    }

    @Test
    fun myWorkAndTaskDetailRespectFollowupCapability() {
        val task = sampleTask()
        val state = sampleState().copy(
            view = "tasks",
            selected = CrmTaskDetail(
                task = task,
                project = CrmProjectSummary(10, "P-10", "城配扩容项目", "active", "完成线路联调"),
            ),
            payload = sampleState().payload.copy(capabilities = ExecutionCapabilities(submitFollowup = false)),
        )
        composeRule.setContent {
            LiquidTheme {
                TaskContent(
                    state = state,
                    onSetView = {},
                    onQueryChange = {},
                    onProjectFilter = {},
                    onTaskFilter = {},
                    onRefresh = {},
                    onOpenTask = {},
                    onCloseTask = {},
                    onFollowup = {},
                    onCreateProject = {},
                )
            }
        }

        composeRule.onNodeWithText("我的工作").assertIsDisplayed()
        composeRule.onNodeWithTag("task-detail-title").assertIsDisplayed()
        composeRule.onNodeWithText("所属项目").assertIsDisplayed()
        composeRule.onNodeWithText("进入跟进填写").assertDoesNotExist()
    }

    private fun sampleState() = TaskUiState(
        payload = ExecutionPayload(
            summary = ExecutionSummary(activeProjects = 1, myOpenTasks = 1),
            projects = ExecutionProjectPage(
                items = listOf(
                    ExecutionProject(
                        id = 10,
                        projectCode = "P-10",
                        projectName = "城配扩容项目",
                        purpose = "完成线路联调",
                        status = "active",
                        taskTotal = 2,
                        taskOpen = 1,
                    )
                ),
                total = 1,
            ),
            myTasks = ExecutionTaskPage(items = listOf(sampleTask()), total = 1),
            capabilities = ExecutionCapabilities(createProject = true, submitFollowup = true),
        )
    )

    private fun sampleTask() = CrmTaskRow(
        id = 20,
        projectId = 10,
        taskCode = "TASK-20",
        customerCode = "C-20",
        customerName = "华南配送客户",
        status = "in_progress",
        latestOwnerNextAction = "确认联调日期",
    )
}
