package com.demo.management.data.local

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(tableName = "offline_customer")
data class OfflineCustomerEntity(
    @PrimaryKey @ColumnInfo(name = "customer_code") val customerCode: String,
    @ColumnInfo(name = "customer_name") val customerName: String,
    @ColumnInfo(name = "payload_json") val payloadJson: String,
    @ColumnInfo(name = "remote_updated_at") val remoteUpdatedAt: String? = null,
    @ColumnInfo(name = "synced_at") val syncedAt: Long,
)

@Entity(
    tableName = "offline_task",
    indices = [Index("customer_code"), Index("status")],
)
data class OfflineTaskEntity(
    @PrimaryKey val id: Long,
    @ColumnInfo(name = "customer_code") val customerCode: String,
    val status: String,
    @ColumnInfo(name = "payload_json") val payloadJson: String,
    @ColumnInfo(name = "remote_updated_at") val remoteUpdatedAt: String? = null,
    @ColumnInfo(name = "synced_at") val syncedAt: Long,
)

/** The database is SQLCipher-backed, so this cached lead payload is encrypted at rest. */
@Entity(
    tableName = "offline_lead",
    indices = [Index("status"), Index("cache_scope")],
)
data class OfflineLeadEntity(
    @PrimaryKey val id: Long,
    @ColumnInfo(name = "lead_name") val leadName: String,
    val status: String,
    @ColumnInfo(name = "payload_json") val payloadJson: String,
    /** Only owned or assigned private leads may be read from this encrypted table. */
    @ColumnInfo(name = "cache_scope", defaultValue = "'legacy'") val cacheScope: String = "legacy",
    @ColumnInfo(name = "remote_updated_at") val remoteUpdatedAt: String? = null,
    @ColumnInfo(name = "synced_at") val syncedAt: Long,
)

@Entity(tableName = "offline_dictionary")
data class OfflineDictionaryEntity(
    @PrimaryKey @ColumnInfo(name = "dictionary_key") val dictionaryKey: String,
    @ColumnInfo(name = "payload_json") val payloadJson: String,
    @ColumnInfo(name = "synced_at") val syncedAt: Long,
)

@Entity(tableName = "sync_cursor")
data class SyncCursorEntity(
    @PrimaryKey val id: String = "default",
    val cursor: String? = null,
    @ColumnInfo(name = "scope_revision") val scopeRevision: String? = null,
    @ColumnInfo(name = "last_synced_at") val lastSyncedAt: Long? = null,
    @ColumnInfo(name = "last_error") val lastError: String? = null,
)

@Entity(
    tableName = "outbox_operation",
    indices = [Index("status"), Index("resource_type", "resource_id")],
)
data class OutboxOperationEntity(
    @PrimaryKey @ColumnInfo(name = "operation_id") val operationId: String,
    @ColumnInfo(name = "action_type") val actionType: String,
    @ColumnInfo(name = "resource_type") val resourceType: String? = null,
    @ColumnInfo(name = "resource_id") val resourceId: String? = null,
    @ColumnInfo(name = "base_updated_at") val baseUpdatedAt: String? = null,
    @ColumnInfo(name = "payload_json") val payloadJson: String,
    @ColumnInfo(name = "attachments_json") val attachmentsJson: String = "[]",
    val status: String = "pending",
    @ColumnInfo(name = "attempt_count") val attemptCount: Int = 0,
    @ColumnInfo(name = "error_code") val errorCode: String? = null,
    @ColumnInfo(name = "error_message") val errorMessage: String? = null,
    @ColumnInfo(name = "created_at") val createdAt: Long = System.currentTimeMillis(),
    @ColumnInfo(name = "updated_at") val updatedAt: Long = System.currentTimeMillis(),
)

@Entity(tableName = "sync_conflict")
data class SyncConflictEntity(
    @PrimaryKey @ColumnInfo(name = "operation_id") val operationId: String,
    @ColumnInfo(name = "resource_type") val resourceType: String? = null,
    @ColumnInfo(name = "resource_id") val resourceId: String? = null,
    @ColumnInfo(name = "conflict_json") val conflictJson: String,
    val status: String = "open",
    @ColumnInfo(name = "created_at") val createdAt: Long = System.currentTimeMillis(),
    @ColumnInfo(name = "resolved_at") val resolvedAt: Long? = null,
)

@Entity(
    tableName = "offline_attachment",
    indices = [Index("operation_id"), Index("status")],
)
data class OfflineAttachmentEntity(
    @PrimaryKey val id: String,
    @ColumnInfo(name = "operation_id") val operationId: String,
    @ColumnInfo(name = "encrypted_path") val encryptedPath: String,
    @ColumnInfo(name = "display_name") val displayName: String,
    @ColumnInfo(name = "mime_type") val mimeType: String? = null,
    @ColumnInfo(name = "size_bytes") val sizeBytes: Long = 0,
    val status: String = "pending",
    @ColumnInfo(name = "created_at") val createdAt: Long = System.currentTimeMillis(),
)
