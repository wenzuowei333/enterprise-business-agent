package com.demo.management

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import com.demo.designsystem.theme.LiquidTheme
import com.demo.management.data.CustomerPanoramaTag
import com.demo.management.data.CustomerPanoramaTags
import com.demo.management.data.LinkedCustomerRow
import com.demo.management.data.MobileCustomerTagPayload
import com.demo.management.data.MobileDeliveryCapabilities
import com.demo.management.data.MobileDeliveryTask
import com.demo.management.feature.collaboration.CustomerTagsContent
import com.demo.management.feature.collaboration.DeliveryContent
import com.demo.management.feature.collaboration.DeliveryUiState
import org.junit.Rule
import org.junit.Test

class FieldCollaborationComposeTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun customerTagsShowCategoryAndReviewWarning() {
        composeRule.setContent {
            LiquidTheme {
                CustomerTagsContent(
                    MobileCustomerTagPayload(
                        customer = LinkedCustomerRow("C-1", "华南城配客户"),
                        tags = CustomerPanoramaTags(
                            items = listOf(CustomerPanoramaTag(id = 1, name = "冷链交接", category = "配送要求", reviewDate = "2026-08-31")),
                            reviewDueCount = 1,
                        ),
                    )
                )
            }
        }

        composeRule.onNodeWithText("配送要求").assertIsDisplayed()
        composeRule.onNodeWithText("冷链交接").assertIsDisplayed()
        composeRule.onNodeWithText("1 项标签需要复核").assertIsDisplayed()
    }

    @Test
    fun deliveryCompletionRequiresExplicitSignatureConfirmation() {
        val delivery = MobileDeliveryTask(
            id = 2,
            deliveryNo = "DEL-2",
            orderId = 3,
            customerName = "华南城配客户",
            status = "delivering",
            deliveryAddress = "测试路 88 号",
            createdAt = "2026-08-31T08:00:00Z",
            updatedAt = "2026-08-31T08:10:00Z",
        )
        composeRule.setContent {
            LiquidTheme {
                DeliveryContent(
                    state = DeliveryUiState(
                        items = listOf(delivery),
                        total = 1,
                        capabilities = MobileDeliveryCapabilities(manage = true),
                        selected = delivery,
                    ),
                    onQuery = {},
                    onSearch = {},
                    onStatus = {},
                    onLoadMore = {},
                    onOpen = {},
                    onClose = {},
                    onSubmit = { _, _, _ -> },
                )
            }
        }

        composeRule.onNodeWithText("完成签收").performClick()
        composeRule.onNodeWithText("签收人").assertIsDisplayed()
        composeRule.onNodeWithText("人工确认").assertIsDisplayed()
    }

    @Test
    fun deliveryViewerCannotSeeWriteActions() {
        val delivery = MobileDeliveryTask(
            id = 3,
            deliveryNo = "DEL-3",
            orderId = 4,
            customerName = "只读配送客户",
            status = "delivering",
            createdAt = "2026-08-31T08:00:00Z",
            updatedAt = "2026-08-31T08:10:00Z",
        )
        composeRule.setContent {
            LiquidTheme {
                DeliveryContent(
                    state = DeliveryUiState(
                        items = listOf(delivery),
                        total = 1,
                        capabilities = MobileDeliveryCapabilities(manage = false),
                        selected = delivery,
                    ),
                    onQuery = {},
                    onSearch = {},
                    onStatus = {},
                    onLoadMore = {},
                    onOpen = {},
                    onClose = {},
                    onSubmit = { _, _, _ -> },
                )
            }
        }

        composeRule.onNodeWithTag("delivery-detail-title").assertIsDisplayed()
        composeRule.onNodeWithText("完成签收").assertDoesNotExist()
        composeRule.onNodeWithText("登记异常").assertDoesNotExist()
    }

    @Test
    fun deliveryConflictRemainsVisibleInsideTheOpenDetail() {
        val delivery = MobileDeliveryTask(
            id = 4,
            deliveryNo = "DEL-4",
            orderId = 5,
            customerName = "冲突测试客户",
            status = "planned",
            createdAt = "2026-08-31T08:00:00Z",
            updatedAt = "2026-08-31T08:10:00Z",
        )
        composeRule.setContent {
            LiquidTheme {
                DeliveryContent(
                    state = DeliveryUiState(
                        items = listOf(delivery),
                        total = 1,
                        capabilities = MobileDeliveryCapabilities(manage = true),
                        selected = delivery,
                        error = "配送任务已更新，请刷新后重试",
                    ),
                    onQuery = {},
                    onSearch = {},
                    onStatus = {},
                    onLoadMore = {},
                    onOpen = {},
                    onClose = {},
                    onSubmit = { _, _, _ -> },
                )
            }
        }

        composeRule.onNodeWithTag("delivery-detail-error").assertIsDisplayed()
    }
}
