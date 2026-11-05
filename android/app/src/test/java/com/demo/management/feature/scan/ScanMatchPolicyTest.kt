package com.demo.management.feature.scan

import com.demo.management.data.round3.ScanMatch
import org.junit.Assert.assertEquals
import org.junit.Test

class ScanMatchPolicyTest {
    @Test
    fun multipleExactMatchesRequireSelection() {
        val matches = listOf(
            ScanMatch("product", "P001", "商品"),
            ScanMatch("customer", "P001", "客户"),
        )
        assertEquals(ScanAction.Select(matches), scanAction(matches))
    }

    @Test
    fun emptyResultFallsBackToManualSearch() {
        assertEquals(ScanAction.ManualSearch, scanAction(emptyList()))
    }
}
