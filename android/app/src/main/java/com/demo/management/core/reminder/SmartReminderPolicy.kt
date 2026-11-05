package com.demo.management.core.reminder

import java.security.MessageDigest

data class LocalReminderRule(
    val type: String,
    val resourceId: String,
    val dueAt: String,
    val title: String = "",
    val completed: Boolean = false,
)

fun reminderIdentity(type: String, resourceId: String, dueAt: String): String {
    val source = "$type|$resourceId|$dueAt"
    return MessageDigest.getInstance("SHA-256")
        .digest(source.toByteArray())
        .joinToString("") { "%02x".format(it) }
}

fun deduplicateActiveReminders(rules: List<LocalReminderRule>): List<LocalReminderRule> =
    rules.filterNot { it.completed }.distinctBy { reminderIdentity(it.type, it.resourceId, it.dueAt) }

fun canUseAiDrafts(role: String, featureFlags: Map<String, Boolean>): Boolean =
    role == "admin" && featureFlags["ai_drafts"] == true
