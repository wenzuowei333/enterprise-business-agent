package com.demo.management.data.round3

import com.squareup.moshi.Json

data class DataModule(
    val key: String,
    val label: String,
    val permission: String,
)

data class DataOverview(
    val modules: List<DataModule> = emptyList(),
    @Json(name = "page_size") val pageSize: Int = 20,
)

data class RecordPage(
    val items: List<Map<String, Any?>> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
    val summary: Map<String, Any?> = emptyMap(),
)

data class InventoryCheckBatch(
    val id: Long,
    @Json(name = "batch_no") val batchNo: String,
    @Json(name = "file_name") val fileName: String,
    @Json(name = "data_date") val dataDate: String? = null,
    val status: String,
    @Json(name = "total_rows") val totalRows: Int = 0,
    @Json(name = "matched_rows") val matchedRows: Int = 0,
    @Json(name = "difference_rows") val differenceRows: Int = 0,
    @Json(name = "missing_in_system_rows") val missingInSystemRows: Int = 0,
    @Json(name = "invalid_rows") val invalidRows: Int = 0,
    @Json(name = "created_at") val createdAt: String? = null,
    @Json(name = "mapping_json") val mapping: Map<String, Any?>? = null,
)

data class InventoryCheckBatchPage(
    val items: List<InventoryCheckBatch> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
)

data class ImportBatch(
    val id: Long,
    @Json(name = "batch_no") val batchNo: String,
    @Json(name = "file_name") val fileName: String,
    @Json(name = "file_type") val fileType: String,
    @Json(name = "data_date") val dataDate: String? = null,
    val status: String,
    @Json(name = "total_rows") val totalRows: Int = 0,
    @Json(name = "success_rows") val successRows: Int = 0,
    @Json(name = "error_rows") val errorRows: Int = 0,
    @Json(name = "mapping_json") val mapping: Map<String, Any?>? = null,
)

data class NotificationCenter(
    val summary: Map<String, Int> = emptyMap(),
    val items: List<MobileNotification> = emptyList(),
    @Json(name = "generated_at") val generatedAt: String? = null,
)

data class MobileNotification(
    @Json(name = "notification_id") val notificationId: String,
    @Json(name = "notification_type") val notificationType: String,
    val title: String,
    val detail: String? = null,
    val status: String = "pending",
    val priority: String = "normal",
    @Json(name = "source_type") val sourceType: String? = null,
    @Json(name = "source_id") val sourceId: String? = null,
    @Json(name = "project_id") val projectId: Long? = null,
    @Json(name = "task_id") val taskId: Long? = null,
    @Json(name = "customer_code") val customerCode: String? = null,
    @Json(name = "action_path") val actionPath: String? = null,
    @Json(name = "created_at") val createdAt: String? = null,
    @Json(name = "due_at") val dueAt: String? = null,
)

data class NotificationActionRequest(
    val action: String = "handled",
    val note: String? = null,
)

data class ScanResult(
    @Json(name = "match_type") val matchType: String,
    val matches: List<ScanMatch> = emptyList(),
    val query: String,
)

data class ScanMatch(
    val type: String,
    val code: String,
    val name: String,
    val barcode: String? = null,
    val target: Map<String, String>? = null,
)

data class DashboardOverview(
    val range: String,
    @Json(name = "date_from") val dateFrom: String,
    @Json(name = "date_to") val dateTo: String,
    val conclusion: String? = null,
    val metrics: List<Map<String, Any?>> = emptyList(),
    val trend: List<Map<String, Any?>> = emptyList(),
    val actions: List<Map<String, Any?>> = emptyList(),
)

data class AssistantRuntime(
    val configured: Boolean = false,
    val provider: String? = null,
    val model: String? = null,
)

data class AssistantMessageRequest(
    val message: String,
    val operation: String? = null,
    val channel: String = "android",
)

data class AssistantMessageResponse(
    val message: Map<String, Any?>,
    val runtime: AssistantRuntime,
    @Json(name = "insights_created") val insightsCreated: Int = 0,
)

data class TelemetryEvent(
    @Json(name = "event_type") val eventType: String,
    @Json(name = "occurred_at") val occurredAt: String,
    @Json(name = "request_id") val requestId: String? = null,
    val route: String? = null,
    val code: String? = null,
    @Json(name = "duration_ms") val durationMs: Int? = null,
    @Json(name = "app_version") val appVersion: String? = null,
    @Json(name = "device_model") val deviceModel: String? = null,
    @Json(name = "android_version") val androidVersion: String? = null,
)

data class TelemetryBatch(
    @Json(name = "installation_id") val installationId: String,
    val events: List<TelemetryEvent>,
)
