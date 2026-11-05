package com.demo.management.core.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MobileUpdatePolicyTest {
    @Test
    fun versionCodeControlsOptionalAndRequiredUpdates() {
        assertEquals(UpdateDecision.None, MobileUpdatePolicy.decide(current = 3, latest = 3, minimum = 1, mode = "optional"))
        assertEquals(UpdateDecision.Optional, MobileUpdatePolicy.decide(current = 2, latest = 3, minimum = 1, mode = "optional"))
        assertEquals(UpdateDecision.Required, MobileUpdatePolicy.decide(current = 1, latest = 3, minimum = 2, mode = "optional"))
        assertEquals(UpdateDecision.Required, MobileUpdatePolicy.decide(current = 2, latest = 3, minimum = 1, mode = "required"))
    }

    @Test
    fun optionalUpdatePromptsUntilCurrentVersionIsDismissed() {
        assertTrue(
            MobileUpdatePolicy.shouldShowOptionalPrompt(
                decision = UpdateDecision.Optional,
                latestVersionCode = 7,
                dismissedVersionCode = null,
            ),
        )
        assertFalse(
            MobileUpdatePolicy.shouldShowOptionalPrompt(
                decision = UpdateDecision.Optional,
                latestVersionCode = 7,
                dismissedVersionCode = 7,
            ),
        )
        assertFalse(
            MobileUpdatePolicy.shouldShowOptionalPrompt(
                decision = UpdateDecision.Required,
                latestVersionCode = 7,
                dismissedVersionCode = null,
            ),
        )
    }
}
