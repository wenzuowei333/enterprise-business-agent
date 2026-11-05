package com.demo.designsystem.theme

enum class LiquidThemeMode(val wireName: String) {
    System("system"),
    Light("light"),
    Dark("dark"),
    ;

    companion object {
        fun fromWireName(value: String?): LiquidThemeMode = entries.firstOrNull { it.wireName == value } ?: System
    }
}

enum class GlassPreference(val wireName: String) {
    Auto("auto"),
    Enhanced("enhanced"),
    Reduced("reduced"),
    Off("off"),
    ;

    companion object {
        fun fromWireName(value: String?): GlassPreference = entries.firstOrNull { it.wireName == value } ?: Auto
    }
}

enum class MotionPreference(val wireName: String) {
    Normal("normal"),
    Reduced("reduced"),
    ;

    companion object {
        fun fromWireName(value: String?): MotionPreference = entries.firstOrNull { it.wireName == value } ?: Normal
    }
}

data class AppearanceSettings(
    val themeMode: LiquidThemeMode,
    val glassPreference: GlassPreference,
    val motionPreference: MotionPreference,
) {
    companion object {
        val Default = AppearanceSettings(
            themeMode = LiquidThemeMode.System,
            glassPreference = GlassPreference.Auto,
            motionPreference = MotionPreference.Normal,
        )
    }
}
