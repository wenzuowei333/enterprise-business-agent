package com.demo.management.feature.data

fun visibleDataSections(
    moduleKeys: Set<String>,
    featureFlags: Map<String, Boolean>,
    isAdmin: Boolean,
): List<String> = buildList {
    if (moduleKeys.isNotEmpty()) add("query")
    if (featureFlags["checks"] == true && moduleKeys.any { it == "inventory_check" || it == "receivable_check" }) add("checks")
    if (featureFlags["manager_dashboard"] == true) add("dashboard")
    if (featureFlags["ai"] == true && isAdmin) add("ai")
}
