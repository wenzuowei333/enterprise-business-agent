package com.demo.designsystem.glass

import com.demo.designsystem.theme.GlassPreference

enum class GlassTier {
    Full,
    Blur,
    Static,
    Solid,
}

data class DeviceGlassCapabilities(
    val sdkInt: Int,
    val isLowRam: Boolean,
    val isPowerSaveMode: Boolean,
    val forceReducedGlass: Boolean,
    val liquidUiEnabled: Boolean,
    val fullEffectEnabled: Boolean,
)

object AdaptiveGlassPolicy {
    fun resolve(
        preference: GlassPreference,
        capabilities: DeviceGlassCapabilities,
    ): GlassTier {
        if (!capabilities.liquidUiEnabled ||
            capabilities.isLowRam ||
            capabilities.isPowerSaveMode ||
            preference == GlassPreference.Off
        ) {
            return GlassTier.Solid
        }
        if (capabilities.forceReducedGlass || preference == GlassPreference.Reduced) {
            return GlassTier.Static
        }
        if (capabilities.sdkInt < 31) {
            return GlassTier.Static
        }
        if (capabilities.sdkInt < 33 || !capabilities.fullEffectEnabled) {
            return GlassTier.Blur
        }
        return GlassTier.Full
    }
}
