package com.demo.management.core.auth

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class InMemoryTokenProviderTest {
    @Test
    fun updateAndClearTokens() {
        val provider = InMemoryTokenProvider()

        provider.update(accessToken = "access", refreshToken = "refresh")
        assertEquals("access", provider.accessToken())
        assertEquals("refresh", provider.refreshToken())

        provider.clear()
        assertNull(provider.accessToken())
        assertNull(provider.refreshToken())
    }
}
