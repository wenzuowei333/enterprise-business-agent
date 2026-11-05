package com.demo.management.feature.lead

import com.demo.management.core.sync.OutboxPolicy
enum class LeadOperationsSection(val label: String) {
    Mine("我的线索"),
    Today("今日待办"),
    DueSoon("即将到期"),
    Overdue("已逾期"),
    ClaimablePool("可认领公海"),
}

fun canOpenLeadOperationsWorkbench(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    LeadOperationsSection.entries.any { canViewLeadOperationsSection(it, permissions, flags) }

fun canViewLeadOperationsSection(
    section: LeadOperationsSection,
    permissions: Collection<String>,
    flags: Map<String, Boolean>,
): Boolean {
    if (flags["lead_pool"] != true) return false
    return when (section) {
        LeadOperationsSection.Mine -> "crm_lead.view" in permissions
        LeadOperationsSection.Today,
        LeadOperationsSection.DueSoon,
        LeadOperationsSection.Overdue -> flags["lead_sla"] == true && "crm_lead.view" in permissions
        LeadOperationsSection.ClaimablePool -> flags["lead_public_pool"] == true &&
            "crm_lead.view" in permissions && "crm_lead.claim" in permissions
    }
}

object LeadOperationsCachePolicy {
    fun canPersist(section: LeadOperationsSection): Boolean = section == LeadOperationsSection.Mine
}

object LeadOperationsOutboxPolicy {
    fun canQueue(actionType: String): Boolean = OutboxPolicy.canQueue(actionType)
}

fun leadSlaStateLabel(value: String?): String = when (value) {
    "overdue" -> "已逾期"
    "due_soon" -> "即将到期"
    "unassigned" -> "待分配"
    else -> "正常"
}
