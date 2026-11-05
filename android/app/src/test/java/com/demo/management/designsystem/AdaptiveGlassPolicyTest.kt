package com.demo.management.designsystem

import com.demo.designsystem.glass.AdaptiveGlassPolicy
import com.demo.designsystem.glass.DeviceGlassCapabilities
import com.demo.designsystem.glass.GlassTier
import com.demo.designsystem.theme.GlassPreference
import org.junit.Assert.assertEquals
import org.junit.Test

class AdaptiveGlassPolicyTest {
    @Test
    fun autoUsesCapabilityBasedEffects() {
        assertEquals(GlassTier.Full, resolve(sdkInt = 35))
        assertEquals(GlassTier.Blur, resolve(sdkInt = 31))
        assertEquals(GlassTier.Static, resolve(sdkInt = 30))
    }

    @Test
    fun lowResourceAndDisabledModesAlwaysUseSolidMaterial() {
        assertEquals(GlassTier.Solid, resolve(sdkInt = 35, isLowRam = true))
        assertEquals(GlassTier.Solid, resolve(sdkInt = 35, isPowerSaveMode = true))
        assertEquals(GlassTier.Solid, resolve(sdkInt = 35, liquidUiEnabled = false))
        assertEquals(GlassTier.Solid, resolve(sdkInt = 35, preference = GlassPreference.Off))
    }

    @Test
    fun remoteReductionAndUserReductionAvoidRealtimeSampling() {
        assertEquals(GlassTier.Static, resolve(sdkInt = 35, forceReducedGlass = true))
        assertEquals(GlassTier.Static, resolve(sdkInt = 35, preference = GlassPreference.Reduced))
        assertEquals(GlassTier.Blur, resolve(sdkInt = 35, fullEffectEnabled = false))
    }

    private fun resolve(
        sdkInt: Int,
        isLowRam: Boolean = false,
        isPowerSaveMode: Boolean = false,
        forceReducedGlass: Boolean = false,
        liquidUiEnabled: Boolean = true,
        fullEffectEnabled: Boolean = true,
        preference: GlassPreference = GlassPreference.Auto,
    ): GlassTier = AdaptiveGlassPolicy.resolve(
        preference = preference,
        capabilities = DeviceGlassCapabilities(
            sdkInt = sdkInt,
            isLowRam = isLowRam,
            isPowerSaveMode = isPowerSaveMode,
            forceReducedGlass = forceReducedGlass,
            liquidUiEnabled = liquidUiEnabled,
            fullEffectEnabled = fullEffectEnabled,
        ),
    )
}
