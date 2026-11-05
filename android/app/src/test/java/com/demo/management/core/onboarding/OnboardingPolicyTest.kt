package com.demo.management.core.onboarding

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OnboardingPolicyTest {
    @Test
    fun showsOnlyWhenEnabledVersionIsNewer() {
        assertTrue(shouldShowOnboarding(enabled = true, configuredVersion = 2, completedVersion = 1))
        assertFalse(shouldShowOnboarding(enabled = true, configuredVersion = 2, completedVersion = 2))
        assertFalse(shouldShowOnboarding(enabled = false, configuredVersion = 3, completedVersion = 0))
    }

    @Test
    fun completionKeyIsScopedToAccount() {
        assertTrue(onboardingCompletionKey(10) != onboardingCompletionKey(11))
    }
}
