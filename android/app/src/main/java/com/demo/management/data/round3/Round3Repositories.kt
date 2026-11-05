package com.demo.management.data.round3

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class DataRepository @Inject constructor(private val api: DataApi) {
    suspend fun overview(): DataOverview = api.overview()

    suspend fun page(module: String, query: String?, dateFrom: String?, dateTo: String?, warehouse: String?, offset: Int): RecordPage = when (module) {
        "customers", "products", "suppliers" -> api.master(module, query.clean(), offset = offset)
        "sales" -> api.sales(query.clean(), dateFrom, dateTo, warehouse.clean(), offset = offset)
        "purchases" -> api.purchases(query.clean(), dateFrom, dateTo, warehouse.clean(), offset = offset)
        "account_ledger" -> api.accountLedger(query.clean(), dateFrom, dateTo, offset = offset)
        "inventory" -> api.inventory(query.clean(), dateFrom, dateTo, warehouse.clean(), offset = offset)
        else -> RecordPage()
    }

    private fun String?.clean(): String? = this?.trim()?.takeIf { it.isNotEmpty() }
}

@Singleton
class CheckRepository @Inject constructor(private val api: CheckApi) {
    suspend fun inventoryBatches(offset: Int = 0): InventoryCheckBatchPage = api.inventoryBatches(offset = offset)
    suspend fun inventoryResults(batchId: Long, type: String?, query: String?, offset: Int = 0): RecordPage = api.inventoryResults(batchId, type, query, offset = offset)
    suspend fun receivableResults(type: String?, query: String?, offset: Int = 0): RecordPage = api.receivableResults(type, query, offset = offset)

    suspend fun uploadInventory(resolver: ContentResolver, uri: Uri, dataDate: String?): InventoryCheckBatch =
        api.uploadInventory(filePart(resolver, uri), dataDate?.toRequestBody("text/plain".toMediaTypeOrNull()))

    suspend fun uploadReceivable(resolver: ContentResolver, uri: Uri, dataDate: String?): ImportBatch =
        api.uploadReceivable(filePart(resolver, uri), dataDate?.toRequestBody("text/plain".toMediaTypeOrNull()))

    suspend fun validateReceivable(batchId: Long): ImportBatch = api.validateReceivable(batchId)
    suspend fun commitReceivable(batchId: Long): ImportBatch = api.commitReceivable(batchId)

    private fun filePart(resolver: ContentResolver, uri: Uri): MultipartBody.Part {
        val name = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0) else null
        } ?: "mobile-upload.xlsx"
        val bytes = resolver.openInputStream(uri)?.use { it.readBytes() } ?: error("无法读取所选文件")
        require(bytes.size <= 30 * 1024 * 1024) { "文件不能超过 30MB" }
        val body = bytes.toRequestBody((resolver.getType(uri) ?: "application/octet-stream").toMediaTypeOrNull())
        return MultipartBody.Part.createFormData("file", name, body)
    }
}

@Singleton
class ToolsRepository @Inject constructor(private val api: ToolsApi) {
    suspend fun notifications(): NotificationCenter = api.notifications()
    suspend fun processNotification(id: String, note: String? = null) = api.processNotification(id, NotificationActionRequest(note = note))
    suspend fun scan(value: String): ScanResult = api.resolveScan(value)
    suspend fun dashboard(range: String): DashboardOverview = api.dashboard(range)
    suspend fun assistantRuntime(): AssistantRuntime = api.assistantRuntime()
    suspend fun assistantMessages(): List<Map<String, Any?>> = api.assistantMessages()
    suspend fun sendAssistant(message: String): AssistantMessageResponse = api.sendAssistantMessage(AssistantMessageRequest(message))
    suspend fun telemetry(installationId: String, events: List<TelemetryEvent>) = api.telemetry(TelemetryBatch(installationId, events))
}
