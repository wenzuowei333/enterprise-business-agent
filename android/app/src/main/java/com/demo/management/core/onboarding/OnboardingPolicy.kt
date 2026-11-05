package com.demo.management.core.onboarding

fun shouldShowOnboarding(enabled: Boolean, configuredVersion: Int, completedVersion: Int): Boolean =
    enabled && configuredVersion > completedVersion

fun onboardingCompletionKey(userId: Long): String = "completed_onboarding_version_$userId"
