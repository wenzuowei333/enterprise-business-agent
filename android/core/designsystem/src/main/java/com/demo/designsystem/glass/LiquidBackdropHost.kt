package com.demo.designsystem.glass

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import android.os.PowerManager
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import com.kyant.backdrop.Backdrop
import com.kyant.backdrop.backdrops.layerBackdrop
import com.kyant.backdrop.backdrops.rememberLayerBackdrop
import com.demo.designsystem.theme.LocalAppearanceSettings
import com.demo.designsystem.theme.LocalLiquidUiConfig

internal val LocalLiquidBackdrop = staticCompositionLocalOf<Backdrop?> { null }
val LocalGlassTier = staticCompositionLocalOf { GlassTier.Solid }

@Composable
fun LiquidBackdropHost(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val settings = LocalAppearanceSettings.current
    val config = LocalLiquidUiConfig.current
    val activityManager = remember(context) {
        context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
    }
    val powerManager = remember(context) {
        context.getSystemService(Context.POWER_SERVICE) as PowerManager
    }
    val tier = AdaptiveGlassPolicy.resolve(
        preference = settings.glassPreference,
        capabilities = DeviceGlassCapabilities(
            sdkInt = Build.VERSION.SDK_INT,
            isLowRam = activityManager.isLowRamDevice,
            isPowerSaveMode = powerManager.isPowerSaveMode,
            forceReducedGlass = config.forceReducedGlass,
            liquidUiEnabled = config.liquidUiEnabled,
            fullEffectEnabled = config.fullEffectEnabled,
        ),
    )
    val backdrop = rememberLayerBackdrop()
    Box(modifier = modifier.fillMaxSize()) {
        // A single page-level sampling layer prevents recursive glass-on-glass rendering.
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(androidx.compose.material3.MaterialTheme.colorScheme.background)
                .layerBackdrop(backdrop),
        )
        CompositionLocalProvider(
            LocalLiquidBackdrop provides backdrop,
            LocalGlassTier provides tier,
        ) {
            content()
        }
    }
}

internal fun solidGlassFallback(tier: GlassTier): Boolean = tier == GlassTier.Solid
