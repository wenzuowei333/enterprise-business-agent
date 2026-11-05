package com.demo.designsystem.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val BrandBlue = Color(0xFF3B82F6)
private val BrandBlueDark = Color(0xFF74A7FF)
private val Success = Color(0xFF16865C)
private val Warning = Color(0xFFD97706)
private val Danger = Color(0xFFDC2626)

private val LiquidTypography = Typography(
    headlineSmall = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 24.sp,
        lineHeight = 30.sp,
        letterSpacing = 0.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 20.sp,
        lineHeight = 26.sp,
        letterSpacing = 0.sp,
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 16.sp,
        lineHeight = 22.sp,
        letterSpacing = 0.sp,
    ),
    bodyLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        letterSpacing = 0.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 21.sp,
        letterSpacing = 0.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Medium,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        letterSpacing = 0.sp,
    ),
)

private val LightColors = lightColorScheme(
    primary = BrandBlue,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFEAF2FF),
    onPrimaryContainer = Color(0xFF12366B),
    secondary = Color(0xFF47617D),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE8EEF5),
    onSecondaryContainer = Color(0xFF24384C),
    tertiary = Success,
    error = Danger,
    background = Color(0xFFF5F7FA),
    onBackground = Color(0xFF18202A),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF18202A),
    surfaceVariant = Color(0xFFEEF2F6),
    onSurfaceVariant = Color(0xFF5F6B7A),
    outline = Color(0xFFD8DEE7),
    outlineVariant = Color(0xFFE7EBF0),
)

private val DarkColors = darkColorScheme(
    primary = BrandBlueDark,
    onPrimary = Color(0xFF082A54),
    primaryContainer = Color(0xFF193C67),
    onPrimaryContainer = Color(0xFFD8E7FF),
    secondary = Color(0xFFA9C1DA),
    onSecondary = Color(0xFF183047),
    secondaryContainer = Color(0xFF293E53),
    onSecondaryContainer = Color(0xFFDCE8F5),
    tertiary = Color(0xFF65D6A6),
    error = Color(0xFFFF8C87),
    background = Color(0xFF101418),
    onBackground = Color(0xFFE7ECF2),
    surface = Color(0xFF171C22),
    onSurface = Color(0xFFE7ECF2),
    surfaceVariant = Color(0xFF222A33),
    onSurfaceVariant = Color(0xFFADB8C5),
    outline = Color(0xFF3B4652),
    outlineVariant = Color(0xFF29323C),
)

@Immutable
data class LiquidUiConfig(
    val liquidUiEnabled: Boolean = true,
    val fullEffectEnabled: Boolean = true,
    val darkThemeEnabled: Boolean = true,
    val forceReducedGlass: Boolean = false,
    val themeVersion: String = "liquid_v1",
)

@Immutable
data class LiquidSemanticColors(
    val success: Color,
    val warning: Color,
    val danger: Color,
    val glassTint: Color,
    val glassBorder: Color,
    val stableSurface: Color,
)

val LocalAppearanceSettings = staticCompositionLocalOf { AppearanceSettings.Default }
val LocalLiquidUiConfig = staticCompositionLocalOf { LiquidUiConfig() }
val LocalLiquidSemanticColors = staticCompositionLocalOf {
    LiquidSemanticColors(Success, Warning, Danger, Color.White, Color.White, Color.White)
}

@Composable
fun LiquidTheme(
    settings: AppearanceSettings = AppearanceSettings.Default,
    config: LiquidUiConfig = LiquidUiConfig(),
    content: @Composable () -> Unit,
) {
    val systemDark = isSystemInDarkTheme()
    val dark = config.darkThemeEnabled && when (settings.themeMode) {
        LiquidThemeMode.System -> systemDark
        LiquidThemeMode.Light -> false
        LiquidThemeMode.Dark -> true
    }
    val colors = if (dark) DarkColors else LightColors
    val semantic = if (dark) {
        LiquidSemanticColors(
            success = Color(0xFF65D6A6),
            warning = Color(0xFFFFB15C),
            danger = Color(0xFFFF8C87),
            glassTint = Color(0x4D202833),
            glassBorder = Color(0x4DFFFFFF),
            stableSurface = Color(0xFF171C22),
        )
    } else {
        LiquidSemanticColors(
            success = Success,
            warning = Warning,
            danger = Danger,
            glassTint = Color(0xB8FFFFFF),
            glassBorder = Color(0xAFFFFFFF),
            stableSurface = Color.White,
        )
    }
    androidx.compose.runtime.CompositionLocalProvider(
        LocalAppearanceSettings provides settings,
        LocalLiquidUiConfig provides config,
        LocalLiquidSemanticColors provides semantic,
    ) {
        MaterialTheme(
            colorScheme = colors,
            typography = LiquidTypography,
            shapes = Shapes(
                extraSmall = RoundedCornerShape(4.dp),
                small = RoundedCornerShape(6.dp),
                medium = RoundedCornerShape(8.dp),
                large = RoundedCornerShape(12.dp),
                extraLarge = RoundedCornerShape(16.dp),
            ),
            content = content,
        )
    }
}
