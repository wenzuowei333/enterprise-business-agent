package com.demo.management.feature.profile

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.demo.designsystem.components.AppScaffold
import com.demo.designsystem.components.ContentSection
import com.demo.designsystem.components.LiquidIconButton
import com.demo.designsystem.components.LiquidSegmentedControl
import com.demo.designsystem.components.LiquidTopBar
import com.demo.designsystem.glass.LocalGlassTier
import com.demo.designsystem.theme.AppearanceSettings
import com.demo.designsystem.theme.GlassPreference
import com.demo.designsystem.theme.LiquidThemeMode
import com.demo.designsystem.theme.MotionPreference

@Composable
fun AppearanceScreen(
    settings: AppearanceSettings,
    onThemeMode: (LiquidThemeMode) -> Unit,
    onGlassPreference: (GlassPreference) -> Unit,
    onMotionPreference: (MotionPreference) -> Unit,
    onClose: () -> Unit,
) {
    AppScaffold(
        topBar = {
            LiquidTopBar(
                title = { Text("外观") },
                navigationIcon = {
                    LiquidIconButton(onClick = onClose) {
                        Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            ContentSection {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("主题", fontWeight = FontWeight.SemiBold)
                    LiquidSegmentedControl(
                        options = listOf(
                            LiquidThemeMode.System to "跟随系统",
                            LiquidThemeMode.Light to "浅色",
                            LiquidThemeMode.Dark to "深色",
                        ),
                        selected = settings.themeMode,
                        onSelected = onThemeMode,
                    )
                }
            }
            ContentSection {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("玻璃效果", fontWeight = FontWeight.SemiBold)
                    LiquidSegmentedControl(
                        options = listOf(
                            GlassPreference.Auto to "自动",
                            GlassPreference.Enhanced to "增强",
                            GlassPreference.Reduced to "简化",
                            GlassPreference.Off to "关闭",
                        ),
                        selected = settings.glassPreference,
                        onSelected = onGlassPreference,
                    )
                    Text(
                        "当前渲染级别：${LocalGlassTier.current.name}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            ContentSection {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("动态效果", fontWeight = FontWeight.SemiBold)
                    LiquidSegmentedControl(
                        options = listOf(
                            MotionPreference.Normal to "正常",
                            MotionPreference.Reduced to "减少动态",
                        ),
                        selected = settings.motionPreference,
                        onSelected = onMotionPreference,
                    )
                }
            }
            Text(
                "低内存、节电模式或远程降级时，系统会自动切换为高对比实色材质，页面布局和功能不变。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}
