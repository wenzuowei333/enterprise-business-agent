package com.demo.management.feature.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate

class DateRangePolicyTest {
    private val today = LocalDate.of(2026, 7, 10)

    @Test
    fun presetsProduceExpectedBusinessRanges() {
        assertEquals(DateRange("2026-07-10", "2026-07-10"), dateRangeForPreset("today", today))
        assertEquals(DateRange("2026-07-09", "2026-07-09"), dateRangeForPreset("yesterday", today))
        assertEquals(DateRange("2026-07-04", "2026-07-10"), dateRangeForPreset("7d", today))
        assertEquals(DateRange("2026-07-01", "2026-07-10"), dateRangeForPreset("month", today))
    }

    @Test
    fun blankCheckDateLetsServerInferDate() {
        assertNull(optionalCheckDate("   "))
        assertEquals("2026-05-31", optionalCheckDate(" 2026-05-31 "))
    }
}
