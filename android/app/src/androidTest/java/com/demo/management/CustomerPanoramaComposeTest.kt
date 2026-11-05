package com.demo.management

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.demo.designsystem.theme.LiquidTheme
import com.demo.management.data.CrmTaskRow
import com.demo.management.data.CustomerPanorama
import com.demo.management.data.CustomerPanoramaProject
import com.demo.management.data.CustomerPanoramaTag
import com.demo.management.data.CustomerPanoramaTags
import com.demo.management.data.CustomerTimelineItem
import com.demo.management.data.LinkedCustomerRow
import com.demo.management.feature.customer.CustomerPanoramaContent
import com.demo.management.feature.customer.CustomerPanoramaUiState
import org.junit.Rule
import org.junit.Test

class CustomerPanoramaComposeTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun panoramaRendersSummaryTagsProjectsTimelineAndOfflineState() {
        composeRule.setContent {
            LiquidTheme {
                CustomerPanoramaContent(
                    state = CustomerPanoramaUiState(
                        panorama = samplePanorama(),
                        offline = true,
                    ),
                    onClose = {},
                    onEditProfile = {},
                    onEditBusinessProfile = {},
                    onTarget = {},
                )
            }
        }

        composeRule.onNodeWithText("华南城配客户").assertIsDisplayed()
        composeRule.onNodeWithText("离线数据").assertIsDisplayed()
        composeRule.onNodeWithText("高频配送").assertIsDisplayed()
        composeRule.onNodeWithText("项目任务").performClick()
        composeRule.onNodeWithText("城配扩容项目").assertIsDisplayed()
        composeRule.onNodeWithText("TASK-101").assertIsDisplayed()
        composeRule.onNodeWithText("时间线").performClick()
        composeRule.onNodeWithText("客户跟进").assertIsDisplayed()
        composeRule.onNodeWithText("已确认下周联调").assertIsDisplayed()
    }

    @Test
    fun onlinePanoramaShowsCustomerTagDetailEntryWhenAllowed() {
        composeRule.setContent {
            LiquidTheme {
                CustomerPanoramaContent(
                    state = CustomerPanoramaUiState(panorama = samplePanorama()),
                    onClose = {},
                    onEditProfile = {},
                    onEditBusinessProfile = {},
                    onTarget = {},
                    canOpenTags = true,
                    onOpenTags = {},
                )
            }
        }

        composeRule.onNodeWithText("查看标签详情").assertIsDisplayed()
    }

    private fun samplePanorama() = CustomerPanorama(
        customer = LinkedCustomerRow(
            customerCode = "C-101",
            customerName = "华南城配客户",
            customerType = "运输企业",
            region = "华南",
            contactName = "陈经理",
            contactPhone = "00000000000",
            customerGroupName = "城配联调群",
            address = "测试路 88 号物流园",
            baseInfoCompleteness = "已完成",
            taskOpen = 1,
        ),
        stats = mapOf("project_total" to 1, "task_open" to 1),
        tags = CustomerPanoramaTags(
            items = listOf(CustomerPanoramaTag(id = 1, name = "高频配送", status = "effective")),
            compatibilityTags = listOf("重点客户"),
        ),
        projects = listOf(
            CustomerPanoramaProject(
                id = 10,
                projectCode = "P-101",
                projectName = "城配扩容项目",
                status = "active",
                taskOpen = 1,
                taskTotal = 2,
            )
        ),
        tasks = listOf(
            CrmTaskRow(
                id = 20,
                projectId = 10,
                taskCode = "TASK-101",
                customerCode = "C-101",
                customerName = "华南城配客户",
                status = "in_progress",
                latestOwnerNextAction = "确认联调时间",
            )
        ),
        timeline = listOf(
            CustomerTimelineItem(
                key = "followup:30",
                kind = "followup",
                title = "客户跟进",
                detail = "已确认下周联调",
                status = "approved",
                occurredAt = "2026-08-31T08:00:00Z",
            )
        ),
    )
}
