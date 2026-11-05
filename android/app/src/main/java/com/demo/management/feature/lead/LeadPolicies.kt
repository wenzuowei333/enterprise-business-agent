package com.demo.management.feature.lead

import com.demo.management.data.round6.LeadCreate
import com.demo.management.data.round6.LeadOfflinePolicy
import com.demo.management.data.round6.LeadProductIntent
import com.demo.management.data.round6.LeadProjectPrefill

data class LeadFormFeatures(
    val productIntentsEnabled: Boolean,
    val offlineDraftsEnabled: Boolean,
)

data class LeadDuplicateDecision(
    val blocksSubmission: Boolean,
    val message: String? = null,
)

data class LeadOcrFields(
    val companyName: String = "",
    val contactName: String = "",
    val contactPhone: String = "",
    val region: String = "",
) {
    fun asMap(): Map<String, String> = mapOf(
        "company_name" to companyName,
        "contact_name" to contactName,
        "contact_phone" to contactPhone,
        "region" to region,
    ).filterValues { it.isNotBlank() }
}

data class ConvertedLeadProjectPrefill(
    val customerCode: String,
    val customerName: String,
    val projectName: String,
    val projectType: String,
    val customerScopeNote: String,
    val businessLine: String,
    val autoCreateProject: Boolean = false,
)

fun canOpenLeadWorkspace(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    flags["lead_pool"] == true && "crm_lead.view" in permissions

fun canCreateLead(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    flags["lead_pool"] == true && "crm_lead.create" in permissions

fun canOpenProjectApplication(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    flags["project_application"] == true && "crm_project.create" in permissions

fun canEditLead(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    flags["lead_pool"] == true && "crm_lead.edit" in permissions

fun canQueueLeadFollowup(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    flags["lead_pool"] == true && flags["lead_offline"] == true && "crm_lead.edit" in permissions

fun canAssignLead(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    flags["lead_pool"] == true && "crm_lead.assign" in permissions

fun canConvertLead(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    flags["lead_pool"] == true && flags["lead_conversion"] == true && "crm_lead.convert" in permissions

fun canUseLeadOcr(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    flags["lead_pool"] == true && flags["lead_ocr"] == true && "crm_lead.create" in permissions

fun canUseProductIntent(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    flags["lead_pool"] == true && flags["lead_product_intent"] == true && "crm_lead.edit" in permissions

fun leadFormFeatures(permissions: Collection<String>, flags: Map<String, Boolean>): LeadFormFeatures =
    LeadFormFeatures(
        productIntentsEnabled = canCreateLead(permissions, flags) && flags["lead_product_intent"] == true,
        offlineDraftsEnabled = canCreateLead(permissions, flags) && LeadOfflinePolicy.isEnabled(flags),
    )

fun leadDuplicateDecision(payload: Map<String, Any?>): LeadDuplicateDecision {
    if (payload["has_blocking_duplicates"] == true) {
        return LeadDuplicateDecision(true, "发现完全重复的线索，请核对后再提交")
    }
    val matches = sequenceOf("exact_matches", "duplicates")
        .flatMap { key -> (payload[key] as? List<*>).orEmpty().asSequence() }
        .mapNotNull { it as? Map<*, *> }
        .toList()
    val exact = matches.any { match ->
        match.values.filterIsInstance<String>().any { value ->
            value.lowercase() in setOf("phone", "exact_phone", "name", "exact_name")
        }
    }
    return if (exact) LeadDuplicateDecision(true, "发现完全重复的线索，请核对后再提交") else LeadDuplicateDecision(false)
}

fun canTransitionLead(from: String, to: String): Boolean = when (from) {
    "new" -> to in setOf("new", "active", "closed", "rejected")
    "active" -> to in setOf("active", "qualified", "closed", "rejected")
    "qualified" -> to in setOf("qualified", "active", "closed", "rejected")
    "conversion_pending" -> to == "conversion_pending"
    "converted", "closed", "rejected" -> to == from
    else -> false
}

fun canRequestLeadConversion(status: String, priorApprovalStatus: String?): Boolean =
    status == "qualified" ||
        (status == "conversion_pending" && priorApprovalStatus in setOf("approved", "rejected", "cancelled", "completed"))

fun newLeadPayload(form: LeadFormSnapshot, productIntentsEnabled: Boolean): LeadCreate = LeadCreate(
    leadName = form.leadName.trim(),
    companyName = form.companyName.trim().ifBlank { null },
    contactName = form.contactName.trim().ifBlank { null },
    contactPhone = form.contactPhone.trim().ifBlank { null },
    source = form.source.trim().ifBlank { null },
    region = form.region.trim().ifBlank { null },
    businessLine = form.businessLine.trim().ifBlank { null },
    intentSummary = form.intentSummary.trim().ifBlank { null },
    status = "new",
    nextFollowupAt = form.nextFollowupAt.trim().ifBlank { null },
    productIntents = if (productIntentsEnabled) {
        form.productName.trim().takeIf { it.isNotEmpty() }?.let {
            listOf(LeadProductIntent(productName = it, note = form.productNote.trim().ifBlank { null }))
        }.orEmpty()
    } else emptyList(),
)

fun mapOcrFieldsForLead(values: Map<String, String>): LeadOcrFields = LeadOcrFields(
    companyName = values.firstNonBlank("company_name", "customer_name", "company"),
    contactName = values.firstNonBlank("contact_name", "name"),
    contactPhone = values.firstNonBlank("contact_phone", "phone"),
    region = values.firstNonBlank("region", "address"),
)

fun applyOcrFieldsToLead(
    current: LeadOcrFields,
    values: Map<String, String>,
    confirmedOverwrite: Boolean,
): LeadOcrFields {
    val ocr = mapOcrFieldsForLead(values)
    fun apply(currentValue: String, candidate: String): String = when {
        candidate.isBlank() -> currentValue
        currentValue.isBlank() || confirmedOverwrite -> candidate
        else -> currentValue
    }
    return LeadOcrFields(
        companyName = apply(current.companyName, ocr.companyName),
        contactName = apply(current.contactName, ocr.contactName),
        contactPhone = apply(current.contactPhone, ocr.contactPhone),
        region = apply(current.region, ocr.region),
    )
}

fun defaultOcrSelection(fields: LeadOcrFields): Set<String> = emptySet()

fun leadDeepLink(sourceId: String?): String? = sourceId
    ?.substringBefore(':')
    ?.toLongOrNull()
    ?.takeIf { it > 0 }
    ?.let { "lead/$it" }

fun projectPrefillForConvertedLead(prefill: LeadProjectPrefill): ConvertedLeadProjectPrefill = ConvertedLeadProjectPrefill(
    customerCode = prefill.customerCode,
    customerName = prefill.customerName,
    projectName = prefill.projectName,
    projectType = prefill.projectType,
    customerScopeNote = prefill.customerScopeNote.orEmpty(),
    businessLine = prefill.businessLine.orEmpty(),
)

internal data class LeadListRequest(
    val generation: Long,
    val requestId: Long,
    val query: String,
    val status: String?,
    val offset: Int,
)

internal fun acceptsLeadListResponse(request: LeadListRequest, activeGeneration: Long, activeRequestId: Long): Boolean =
    request.generation == activeGeneration && request.requestId == activeRequestId

private fun Map<String, String>.firstNonBlank(vararg keys: String): String =
    keys.asSequence().mapNotNull(::get).firstOrNull(String::isNotBlank).orEmpty()
