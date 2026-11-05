package com.demo.management.core.update

enum class UpdateDecision { None, Optional, Required }

object MobileUpdatePolicy {
    fun decide(current: Int, latest: Int, minimum: Int, mode: String): UpdateDecision = when {
        current < minimum -> UpdateDecision.Required
        current < latest && mode == "required" -> UpdateDecision.Required
        current < latest -> UpdateDecision.Optional
        else -> UpdateDecision.None
    }

    fun shouldShowOptionalPrompt(
        decision: UpdateDecision,
        latestVersionCode: Int,
        dismissedVersionCode: Int?,
    ): Boolean = decision == UpdateDecision.Optional && dismissedVersionCode != latestVersionCode
}
