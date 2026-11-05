package com.demo.management.data.round5

import com.squareup.moshi.Json

data class FeedbackCreate(
    val category: String,
    val description: String,
    @Json(name = "current_route") val currentRoute: String? = null,
    @Json(name = "request_id") val requestId: String? = null,
    @Json(name = "app_version") val appVersion: String? = null,
    @Json(name = "android_version") val androidVersion: String? = null,
    @Json(name = "device_model") val deviceModel: String? = null,
    @Json(name = "screenshot_path") val screenshotPath: String? = null,
)

data class FeedbackUpdate(val status: String, val resolution: String? = null)

data class FeedbackRow(
    val id: Long,
    @Json(name = "user_id") val userId: Long,
    @Json(name = "user_label") val userLabel: String? = null,
    val category: String,
    val description: String,
    @Json(name = "current_route") val currentRoute: String? = null,
    @Json(name = "request_id") val requestId: String? = null,
    @Json(name = "app_version") val appVersion: String? = null,
    @Json(name = "android_version") val androidVersion: String? = null,
    @Json(name = "device_model") val deviceModel: String? = null,
    @Json(name = "screenshot_path") val screenshotPath: String? = null,
    val status: String,
    @Json(name = "handler_label") val handlerLabel: String? = null,
    val resolution: String? = null,
    @Json(name = "created_at") val createdAt: String,
)

data class FeedbackPage(
    val items: List<FeedbackRow> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
)

data class FeedbackAttachment(@Json(name = "screenshot_path") val screenshotPath: String, @Json(name = "size_bytes") val sizeBytes: Long)

data class AssistantDraftRequest(
    val text: String? = null,
    @Json(name = "task_id") val taskId: Long? = null,
    @Json(name = "approval_id") val approvalId: Long? = null,
    @Json(name = "project_id") val projectId: Long? = null,
    @Json(name = "context_revision") val contextRevision: String? = null,
)

data class AssistantDraftResponse(
    @Json(name = "draft_id") val draftId: String,
    @Json(name = "draft_type") val draftType: String,
    val fields: Map<String, Any?> = emptyMap(),
    val warnings: List<String> = emptyList(),
    @Json(name = "source_refs") val sourceRefs: List<String> = emptyList(),
    val model: String? = null,
    @Json(name = "generated_at") val generatedAt: String,
)

data class AdoptionOverview(
    val days: Int,
    @Json(name = "eligible_users") val eligibleUsers: Int = 0,
    @Json(name = "weekly_active_users") val weeklyActiveUsers: Int = 0,
    @Json(name = "weekly_active_rate") val weeklyActiveRate: Double = 0.0,
    @Json(name = "feature_usage") val featureUsage: Map<String, Int> = emptyMap(),
    @Json(name = "followup_form_avg_ms") val followupFormAvgMs: Long? = null,
    @Json(name = "followup_form_p50_ms") val followupFormP50Ms: Long? = null,
    val feedback: Map<String, Int> = emptyMap(),
    @Json(name = "feedback_resolution_avg_hours") val feedbackResolutionAvgHours: Double? = null,
    @Json(name = "ai_draft_success_rate") val aiDraftSuccessRate: Double? = null,
    @Json(name = "ai_draft_adoption_rate") val aiDraftAdoptionRate: Double? = null,
)
