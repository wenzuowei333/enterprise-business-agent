package com.demo.management.feature.data

import org.junit.Assert.assertEquals
import org.junit.Test

class DataModulePolicyTest {
    @Test
    fun sectionsFollowServerModulesAndFeatureFlags() {
        val sections = visibleDataSections(
            moduleKeys = setOf("customers", "sales", "inventory_check"),
            featureFlags = mapOf("checks" to true, "manager_dashboard" to true, "ai" to false),
            isAdmin = true,
        )
        assertEquals(listOf("query", "checks", "dashboard"), sections)
    }

    @Test
    fun aiRequiresAdminAndFeatureFlag() {
        assertEquals(
            listOf("query"),
            visibleDataSections(setOf("sales"), mapOf("ai" to true), isAdmin = false),
        )
    }
}
