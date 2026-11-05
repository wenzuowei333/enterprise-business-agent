package com.demo.management.core.telemetry

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class TelemetryPolicyTest {
    @Test
    fun stripsQueryAndIdentifiersFromRecordedRoute() {
        val route = sanitizedTelemetryRoute("https://example.invalid/api/v1/mobile/data/sales?q=张三&customer_code=KH001")
        assertEquals("/api/v1/mobile/data/sales", route)
        assertFalse(route.contains("张三"))
        assertFalse(route.contains("KH001"))
    }

    @Test
    fun nonMobileRoutesAreReducedToPathOnly() {
        assertEquals("/health", sanitizedTelemetryRoute("https://example.invalid/health?token=secret"))
    }
}
