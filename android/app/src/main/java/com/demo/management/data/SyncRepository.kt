package com.demo.management.data

import androidx.room.withTransaction
import com.demo.management.core.auth.SecureSessionStore
import com.demo.management.core.sync.OfflineCachePolicy
import com.demo.management.core.sync.OutboxPolicy
import com.demo.management.data.local.AppDatabase
import com.demo.management.data.local.ConflictDao
import com.demo.management.data.local.OfflineCustomerEntity
import com.demo.management.data.local.OfflineDictionaryEntity
import com.demo.management.data.local.OfflineTaskEntity
import com.demo.management.data.round6.LeadRow
import com.demo.management.data.round6.LeadOfflinePolicy
import com.demo.management.data.round6.toOfflineEntity
import com.demo.management.data.local.OutboxDao
import com.demo.management.data.local.OutboxOperationEntity
import com.demo.management.data.local.SyncConflictEntity
import com.demo.management.data.local.SyncCursorEntity
import com.demo.management.data.local.SyncStateDao
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import kotlinx.coroutines.flow.Flow
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.util.UUID
import android.net.Uri
import com.demo.management.core.sync.EncryptedAttachmentStore
import javax.inject.Inject
import javax.inject.Singleton

data class LocalSyncSummary(
    val pending: Int,
    val retryable: Int,
    val conflicts: Int,
    val rejected: Int,
    val lastSyncedAt: Long?,
    val lastError: String?,
)

@Singleton
class SyncRepository @Inject constructor(
    private val api: SyncApi,
    private val database: AppDatabase,
    private val syncState: SyncStateDao,
    private val outbox: OutboxDao,
    private val conflicts: ConflictDao,
    private val sessionStore: SecureSessionStore,
    private val attachmentStore: EncryptedAttachmentStore,
    moshi: Moshi,
) {
    private val customerAdapter = moshi.adapter(LinkedCustomerRow::class.java)
    private val taskAdapter = moshi.adapter(CrmTaskRow::class.java)
    private val leadAdapter = moshi.adapter(LeadRow::class.java)
    private val bootstrapAdapter = moshi.adapter(BootstrapPayload::class.java)
    @Suppress("UNCHECKED_CAST")
    private val mapAdapter = moshi.adapter<Map<String, Any?>>(
        Types.newParameterizedType(Map::class.java, String::class.java, Any::class.java),
    )

    suspend fun pull(): SyncPullPayload {
        val previous = syncState.current()
        val response = api.pull(previous?.cursor, previous?.scopeRevision, sessionStore.deviceId())
        val now = System.currentTimeMillis()
        val leadOfflineEnabled = leadOfflineEnabled()
        val currentUserId = currentMobileUserId()
        val eligibleLeads = currentUserId?.let { LeadOfflinePolicy.eligibleRowsForCache(response.upserts.leads, it) }.orEmpty()
        database.withTransaction {
            val customerRows = response.upserts.customers.map { row ->
                OfflineCustomerEntity(
                    customerCode = row.customerCode,
                    customerName = row.customerName,
                    payloadJson = customerAdapter.toJson(row),
                    remoteUpdatedAt = row.customerUpdatedAt ?: row.lastActivityAt ?: row.profileUpdatedAt,
                    syncedAt = now,
                )
            }
            val taskRows = response.upserts.tasks.map { row ->
                OfflineTaskEntity(
                    id = row.id,
                    customerCode = row.customerCode,
                    status = row.status,
                    payloadJson = taskAdapter.toJson(row),
                    remoteUpdatedAt = row.updatedAt,
                    syncedAt = now,
                )
            }
            if (customerRows.isNotEmpty()) database.offlineDao().saveCustomers(customerRows)
            if (taskRows.isNotEmpty()) database.offlineDao().saveTasks(taskRows)
            if (leadOfflineEnabled && currentUserId != null) {
                val ineligibleLeadIds = response.upserts.leads.map { it.id } - eligibleLeads.map { it.id }.toSet()
                val leadRows = eligibleLeads.map { row ->
                    row.toOfflineEntity(leadAdapter.toJson(row), now)
                }
                if (leadRows.isNotEmpty()) database.offlineDao().saveLeads(leadRows)
                if (ineligibleLeadIds.isNotEmpty()) database.offlineDao().deleteLeads(ineligibleLeadIds.toList())
                val deletedLeadIds = response.deletions.leads.mapNotNull(String::toLongOrNull)
                if (deletedLeadIds.isNotEmpty()) database.offlineDao().deleteLeads(deletedLeadIds)
            } else {
                database.offlineDao().deleteLeads()
            }
            database.offlineDao().saveDictionary(
                OfflineDictionaryEntity("mobile", JSONObject(response.dictionary).toString(), now)
            )
            if (response.fullSnapshot) {
                val customerCodes = response.authoritativeKeys.customers
                val taskIds = response.authoritativeKeys.tasks.mapNotNull(String::toLongOrNull)
                if (customerCodes.isEmpty()) database.offlineDao().deleteCustomers()
                else database.offlineDao().deleteCustomersNotIn(customerCodes)
                if (taskIds.isEmpty()) database.offlineDao().deleteTasks()
                else database.offlineDao().deleteTasksNotIn(taskIds)
                if (leadOfflineEnabled) {
                    val leadIds = if (currentUserId == null) emptyList() else eligibleLeads.map { it.id }
                    if (leadIds.isEmpty()) database.offlineDao().deleteLeads()
                    else database.offlineDao().deleteLeadsNotIn(leadIds)
                }
            }
            syncState.save(
                SyncCursorEntity(
                    cursor = response.nextCursor,
                    scopeRevision = response.scopeRevision,
                    lastSyncedAt = now,
                )
            )
        }
        return response
    }

    suspend fun recordPullFailure(message: String) {
        val current = syncState.current() ?: SyncCursorEntity()
        syncState.save(current.copy(lastError = message))
    }

    suspend fun enqueue(
        actionType: String,
        resourceType: String?,
        resourceId: String?,
        baseUpdatedAt: String?,
        payload: Map<String, Any?>,
        attachments: List<Map<String, Any?>> = emptyList(),
        operationId: String = UUID.randomUUID().toString(),
    ): String {
        require(OutboxPolicy.canQueue(actionType)) { "该线索操作必须在线完成，不能加入待同步队列" }
        outbox.save(
            OutboxOperationEntity(
                operationId = operationId,
                actionType = actionType,
                resourceType = resourceType,
                resourceId = resourceId,
                baseUpdatedAt = baseUpdatedAt,
                payloadJson = mapAdapter.toJson(payload),
                attachmentsJson = JSONArray(attachments).toString(),
            )
        )
        return operationId
    }

    suspend fun syncPending(): List<SyncOperationResult> {
        val rows = outbox.pending()
        if (rows.isEmpty()) {
            syncAttachments()
            return emptyList()
        }
        return submit(rows)
    }

    suspend fun submit(operationId: String): SyncOperationResult? {
        val row = outbox.find(operationId) ?: return null
        return submit(listOf(row)).singleOrNull()
    }

    private suspend fun submit(rows: List<OutboxOperationEntity>): List<SyncOperationResult> {
        val requests = rows.map { row ->
            SyncOperationRequest(
                clientOperationId = row.operationId,
                deviceId = sessionStore.deviceId(),
                actionType = row.actionType,
                resourceType = row.resourceType,
                resourceId = row.resourceId,
                baseUpdatedAt = row.baseUpdatedAt,
                payload = mapAdapter.fromJson(row.payloadJson).orEmpty(),
                attachments = jsonArrayToMaps(row.attachmentsJson),
                createdAt = Instant.ofEpochMilli(row.createdAt).toString(),
            )
        }
        val response = api.operations(SyncOperationBatch(requests))
        val now = System.currentTimeMillis()
        database.withTransaction {
            response.items.forEach { result ->
                val row = outbox.find(result.clientOperationId) ?: return@forEach
                val errorCode = result.error?.get("code")?.toString()
                val errorMessage = result.error?.get("message")?.toString()
                outbox.save(
                    row.copy(
                        status = result.status,
                        resourceType = result.resourceType ?: row.resourceType,
                        resourceId = result.resourceId ?: row.resourceId,
                        attemptCount = row.attemptCount + 1,
                        errorCode = errorCode,
                        errorMessage = errorMessage,
                        updatedAt = now,
                    )
                )
                if (result.status == "conflict") {
                    conflicts.save(
                        SyncConflictEntity(
                            operationId = row.operationId,
                            resourceType = result.resourceType,
                            resourceId = result.resourceId,
                            conflictJson = mapAdapter.toJson(result.result.orEmpty()),
                        )
                    )
                }
            }
        }
        syncAttachments()
        return response.items
    }

    suspend fun queueAttachments(operationId: String, uris: List<Uri>) {
        if (uris.isNotEmpty()) attachmentStore.storeAll(operationId, uris)
    }

    suspend fun queueAndUploadApprovalAttachments(approvalId: Long, uris: List<Uri>): Boolean {
        if (uris.isEmpty()) return true
        val operationId = "approval:$approvalId"
        attachmentStore.storeAll(operationId, uris)
        return attachmentStore.uploadForApproval(operationId, approvalId)
    }

    private suspend fun syncAttachments() {
        attachmentStore.pending().groupBy { it.operationId }.forEach { (operationId, _) ->
            val approvalId = if (operationId.startsWith("approval:")) {
                operationId.substringAfter(':').toLongOrNull()
            } else {
                val row = outbox.find(operationId)
                if (row?.status == "applied" && row.resourceType == "approval_instance") row.resourceId?.toLongOrNull() else null
            }
            if (approvalId != null) attachmentStore.uploadForApproval(operationId, approvalId)
        }
    }

    suspend fun summary(): LocalSyncSummary {
        val state = syncState.current()
        return LocalSyncSummary(
            pending = outbox.count("pending") + outbox.count("processing"),
            retryable = outbox.count("retryable_error"),
            conflicts = outbox.count("conflict"),
            rejected = outbox.count("rejected"),
            lastSyncedAt = state?.lastSyncedAt,
            lastError = state?.lastError,
        )
    }

    suspend fun recentOperations(): List<OutboxOperationEntity> = outbox.recent()
    suspend fun openConflicts(): List<SyncConflictEntity> = conflicts.open()
    fun pendingCount(): Flow<Int> = outbox.observePendingCount()
    fun conflictCount(): Flow<Int> = conflicts.observeOpenCount()
    suspend fun cancel(operationId: String): Boolean {
        val cancelled = outbox.cancelPending(operationId) > 0
        if (cancelled) attachmentStore.deleteForOperation(operationId)
        return cancelled
    }

    suspend fun devices(): MobileDevicePage = api.devices(sessionStore.deviceId())

    suspend fun revokeDevice(sessionId: Long) {
        api.revokeDevice(sessionId)
    }

    suspend fun updateNotificationPreferences(
        sessionId: Long,
        approval: Boolean,
        task: Boolean,
        risk: Boolean,
    ): MobileDevice = api.updateNotifications(
        sessionId,
        NotificationPreferencesUpdate(approval, task, risk),
    )

    suspend fun keepServer(operationId: String) {
        val row = outbox.find(operationId) ?: return
        outbox.save(row.copy(status = "cancelled", updatedAt = System.currentTimeMillis()))
        conflicts.resolve(operationId)
    }

    suspend fun retryWithServerBase(operationId: String) {
        val row = outbox.find(operationId) ?: return
        val conflict = conflicts.open().firstOrNull { it.operationId == operationId } ?: return
        val details = mapAdapter.fromJson(conflict.conflictJson).orEmpty()
        val conflictRows = details["conflicts"] as? List<*> ?: emptyList<Any?>()
        val payload = mapAdapter.fromJson(row.payloadJson).orEmpty().toMutableMap()
        val baseValues = (payload["base_values"] as? Map<*, *>)?.mapKeys { it.key.toString() }?.toMutableMap() ?: mutableMapOf()
        var newest: String? = row.baseUpdatedAt
        conflictRows.filterIsInstance<Map<*, *>>().forEach { item ->
            val field = item["field"]?.toString() ?: return@forEach
            baseValues[field] = item["server_value"]
            newest = item["server_updated_at"]?.toString() ?: newest
        }
        payload["base_values"] = baseValues
        outbox.save(
            row.copy(
                baseUpdatedAt = newest,
                payloadJson = mapAdapter.toJson(payload),
                status = "pending",
                errorCode = null,
                errorMessage = null,
                updatedAt = System.currentTimeMillis(),
            )
        )
        conflicts.resolve(operationId)
    }

    suspend fun cacheIsReadable(): Boolean = OfflineCachePolicy.canRead(syncState.current()?.lastSyncedAt)

    suspend fun canReadLeadCache(): Boolean = leadOfflineEnabled()

    suspend fun applyBootstrapFeatureFlags(featureFlags: Map<String, Boolean>) {
        if (!LeadOfflinePolicy.isEnabled(featureFlags)) clearLeadCache()
    }

    suspend fun clearLocalData() {
        attachmentStore.clearFiles()
        database.withTransaction {
            database.offlineDao().deleteCustomers()
            database.offlineDao().deleteTasks()
            database.offlineDao().deleteLeads()
            database.offlineDao().deleteDictionaries()
            database.syncStateDao().clear()
            database.outboxDao().deleteAll()
            database.conflictDao().deleteAll()
            database.offlineAttachmentDao().deleteAll()
        }
    }

    private suspend fun clearLeadCache() {
        database.withTransaction { database.offlineDao().deleteLeads() }
    }

    private fun leadOfflineEnabled(): Boolean = LeadOfflinePolicy.isEnabled(
        sessionStore.bootstrap()?.let { bootstrapAdapter.fromJson(it)?.app?.featureFlags }.orEmpty(),
    )

    private fun currentMobileUserId(): Long? = sessionStore.bootstrap()
        ?.let { bootstrapAdapter.fromJson(it)?.user?.id }

    private fun jsonArrayToMaps(value: String): List<Map<String, Any?>> {
        val array = runCatching { JSONArray(value) }.getOrNull() ?: return emptyList()
        return (0 until array.length()).mapNotNull { index ->
            val item = array.optJSONObject(index) ?: return@mapNotNull null
            mapAdapter.fromJson(item.toString())
        }
    }
}
