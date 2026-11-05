package com.demo.management

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performScrollToIndex
import com.demo.designsystem.theme.LiquidTheme
import com.demo.management.data.WorkbenchPayload
import com.demo.management.data.WorkbenchQueue
import com.demo.management.data.WorkbenchQueueItem
import com.demo.management.data.WorkbenchShortcuts
import com.demo.management.data.WorkbenchSummary
import com.demo.management.feature.workbench.WorkbenchScreen
import org.junit.Rule
import org.junit.Test

class WorkbenchComposeTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun fieldWorkbenchRendersActionFirstHierarchy() {
        composeRule.setContent {
            LiquidTheme {
                WorkbenchScreen(
                    payload = WorkbenchPayload(
                        dateLabel = "8月31日",
                        headline = "今天有 2 个项目在执行中",
                        summary = WorkbenchSummary(activeProjects = 2, pendingApprovals = 1, overdueTasks = 1),
                        todayQueue = WorkbenchQueue(
                            items = listOf(
                                WorkbenchQueueItem(
                                    key = "task:1",
                                    kind = "task_overdue",
                                    title = "华南配送客户",
                                    subtitle = "确认下一步跟进时间",
                                    statusLabel = "已超期",
                                    tone = "bad",
                                )
                            ),
                            total = 1,
                        ),
                        shortcuts = WorkbenchShortcuts(createProject = true, viewApprovals = true),
                    ),
                    loading = false,
                    onCreateProject = {},
                    onOpenProjects = {},
                    onOpenApprovals = {},
                    onOpenWorkItems = {},
                    onTarget = {},
                )
            }
        }

        composeRule.onNodeWithText("今天有 2 个项目在执行中").assertIsDisplayed()
        composeRule.onNodeWithText("今天要处理").assertIsDisplayed()
        composeRule.onNodeWithTag("workbench-list").performScrollToIndex(4)
        composeRule.onNodeWithText("华南配送客户").assertIsDisplayed()
        composeRule.onNodeWithTag("workbench-queue-item:task:1").assertIsDisplayed()
        composeRule
            .onNodeWithTag("workbench-queue-status:task:1", useUnmergedTree = true)
            .assertTextEquals("已超期")
    }
}
