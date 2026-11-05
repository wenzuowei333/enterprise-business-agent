package com.demo.management.designsystem

import com.demo.designsystem.theme.AppearanceSettings
import com.demo.designsystem.theme.GlassPreference
import com.demo.designsystem.theme.LiquidThemeMode
import com.demo.designsystem.theme.MotionPreference
import org.junit.Assert.assertEquals
import org.junit.Test

class AppearanceSettingsTest {
    @Test
    fun defaultsFollowSystemAndAdaptToDevice() {
        assertEquals(
            AppearanceSettings(
                themeMode = LiquidThemeMode.System,
                glassPreference = GlassPreference.Auto,
                motionPreference = MotionPreference.Normal,
            ),
            AppearanceSettings.Default,
        )
    }

    @Test
    fun persistedValuesUseStableWireNames() {
        assertEquals("system", LiquidThemeMode.System.wireName)
        assertEquals("enhanced", GlassPreference.Enhanced.wireName)
        assertEquals("reduced", MotionPreference.Reduced.wireName)
    }
}
