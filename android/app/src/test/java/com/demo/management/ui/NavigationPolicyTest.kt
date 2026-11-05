package com.demo.management.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class NavigationPolicyTest {
    @Test
    fun incompleteFeaturesDoNotLeaveEmptyTabs() {
        assertEquals(listOf("home"), visibleTabKeys(emptyMap(), emptyList()))
    }

    @Test
    fun completedCrmFeaturesAppearInFixedOrder() {
        assertEquals(
            listOf("home", "customers", "projects"),
            visibleTabKeys(
                mapOf("crm_tasks" to true, "crm_customers" to true),
                listOf("customer.view", "crm_task.view"),
            ),
        )
    }

    @Test
    fun leadOnlyAccountCanReachCustomerWorkspace() {
        assertEquals(
            listOf("home", "customers"),
            visibleTabKeys(
                featureFlags = mapOf("lead_pool" to true),
                permissions = listOf("crm_lead.view"),
                serverNavigation = listOf("home", "customers"),
            ),
        )
    }

    @Test
    fun fulfillmentOnlyAccountCanReachProjectWorkspace() {
        assertEquals(
            listOf("home", "projects"),
            visibleTabKeys(
                featureFlags = mapOf("fulfillment" to true),
                permissions = listOf("delivery.view"),
                serverNavigation = listOf("home", "projects"),
            ),
        )
    }

    @Test
    fun fiveBusinessTabsFollowTheFrozenOrder() {
        assertEquals(
            listOf("home", "customers", "projects", "approvals", "data"),
            visibleTabKeys(
                mapOf("crm_tasks" to true, "crm_customers" to true, "crm_approvals" to true, "data_query" to true),
                listOf("customer.view", "crm_task.view", "approval.view", "sales_detail.view"),
            ),
        )
    }

    @Test
    fun serverNavigationCanFurtherRestrictTabs() {
        assertEquals(
            listOf("home", "approvals"),
            visibleTabKeys(
                mapOf("crm_tasks" to true, "crm_approvals" to true),
                listOf("crm_task.view", "approval.view"),
                listOf("home", "approvals"),
            ),
        )
    }

    @Test
    fun exceptionCenterReplacesDataAsTheFifthTab() {
        assertEquals(
            listOf("home", "exceptions"),
            visibleTabKeys(
                featureFlags = mapOf("data_query" to true, "exception_center" to true),
                permissions = listOf("inventory_snapshot.view", "exception_center.view"),
                serverNavigation = listOf("home", "exceptions"),
            ),
        )
    }

    @Test
    fun legacyTaskRouteMovesToProjects() {
        assertEquals("projects", canonicalMobileRoute("tasks"))
        assertEquals("me", canonicalMobileRoute("me"))
    }
}
