package com.demo.management.core.auth

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkerSessionPolicyTest {
    @Test
    fun restoresEncryptedTokensIntoMemoryForBackgroundWorker() {
        val provider = InMemoryTokenProvider()
        assertTrue(hydrateTokenProvider("access", "refresh", provider))
        assertTrue(provider.accessToken() == "access" && provider.refreshToken() == "refresh")
    }

    @Test
    fun refusesIncompleteStoredSession() {
        val provider = InMemoryTokenProvider()
        assertFalse(hydrateTokenProvider(null, "refresh", provider))
        assertFalse(hydrateTokenProvider("access", null, provider))
    }
}
