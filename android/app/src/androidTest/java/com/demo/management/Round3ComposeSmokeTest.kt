package com.demo.management

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Assignment
import androidx.compose.material.icons.automirrored.outlined.FactCheck
import androidx.compose.material.icons.outlined.Groups
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import com.demo.designsystem.components.LiquidBottomBar
import com.demo.designsystem.components.LiquidNavigationItem
import com.demo.designsystem.theme.LiquidTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class Round3ComposeSmokeTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun composeRuntimeRendersChineseBusinessText() {
        composeRule.setContent { MaterialTheme { Text("数据与现场协同") } }
        composeRule.onNodeWithText("数据与现场协同").assertIsDisplayed()
    }

    @Test
    fun bottomNavigationStaysAboveSystemNavigationArea() {
        var safeBottomPx = 0
        composeRule.setContent {
            val density = LocalDensity.current
            val safeDrawingInsets = WindowInsets.safeDrawing
            SideEffect {
                safeBottomPx = safeDrawingInsets.getBottom(density)
            }
            LiquidTheme {
                Box(modifier = Modifier.fillMaxSize()) {
                    LiquidBottomBar(
                        items = listOf(
                            LiquidNavigationItem("home", "首页", Icons.Outlined.Home),
                            LiquidNavigationItem("customers", "客户", Icons.Outlined.Groups),
                            LiquidNavigationItem("projects", "项目", Icons.AutoMirrored.Outlined.Assignment),
                            LiquidNavigationItem("approvals", "审批", Icons.AutoMirrored.Outlined.FactCheck),
                            LiquidNavigationItem("data", "数据", Icons.Outlined.Storage),
                        ),
                        selectedKey = "home",
                        onSelected = {},
                        modifier = Modifier.align(Alignment.BottomCenter),
                    )
                }
            }
        }

        composeRule.waitForIdle()
        val rootBottom = composeRule.onRoot().fetchSemanticsNode().boundsInRoot.bottom
        val home = composeRule.onNodeWithTag("liquid-bottom-nav-home")
            .assertIsDisplayed()
            .assertHeightIsAtLeast(56.dp)
            .fetchSemanticsNode()

        assertTrue(
            "Bottom navigation item must stay above the safe drawing inset",
            home.boundsInRoot.bottom <= rootBottom - safeBottomPx + 1f,
        )
    }
}
