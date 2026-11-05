package com.demo.management.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface OfflineDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun saveCustomers(rows: List<OfflineCustomerEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun saveTasks(rows: List<OfflineTaskEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun saveLeads(rows: List<OfflineLeadEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun saveDictionary(row: OfflineDictionaryEntity)

    @Query("SELECT * FROM offline_customer ORDER BY customer_name, customer_code")
    suspend fun customers(): List<OfflineCustomerEntity>

    @Query("SELECT * FROM offline_customer WHERE customer_code = :code LIMIT 1")
    suspend fun customer(code: String): OfflineCustomerEntity?

    @Query("SELECT * FROM offline_task ORDER BY synced_at DESC, id DESC")
    suspend fun tasks(): List<OfflineTaskEntity>

    @Query("SELECT * FROM offline_task WHERE id = :id LIMIT 1")
    suspend fun task(id: Long): OfflineTaskEntity?

    @Query("SELECT * FROM offline_task WHERE customer_code = :customerCode ORDER BY synced_at DESC")
    suspend fun tasksForCustomer(customerCode: String): List<OfflineTaskEntity>

    @Query("SELECT * FROM offline_lead WHERE cache_scope IN ('owned', 'assigned') ORDER BY synced_at DESC, id DESC")
    suspend fun leads(): List<OfflineLeadEntity>

    @Query("SELECT * FROM offline_lead WHERE id = :id AND cache_scope IN ('owned', 'assigned') LIMIT 1")
    suspend fun lead(id: Long): OfflineLeadEntity?

    @Query("DELETE FROM offline_customer WHERE customer_code NOT IN (:codes)")
    suspend fun deleteCustomersNotIn(codes: List<String>)

    @Query("DELETE FROM offline_task WHERE id NOT IN (:ids)")
    suspend fun deleteTasksNotIn(ids: List<Long>)

    @Query("DELETE FROM offline_lead WHERE id NOT IN (:ids)")
    suspend fun deleteLeadsNotIn(ids: List<Long>)

    @Query("DELETE FROM offline_lead WHERE id IN (:ids)")
    suspend fun deleteLeads(ids: List<Long>)

    @Query("DELETE FROM offline_customer")
    suspend fun deleteCustomers()

    @Query("DELETE FROM offline_task")
    suspend fun deleteTasks()

    @Query("DELETE FROM offline_lead")
    suspend fun deleteLeads()

    @Query("DELETE FROM offline_dictionary")
    suspend fun deleteDictionaries()

    @Query("SELECT MAX(synced_at) FROM offline_customer")
    suspend fun latestCustomerSync(): Long?

    @Query("SELECT MAX(synced_at) FROM offline_task")
    suspend fun latestTaskSync(): Long?

    @Query("SELECT MAX(synced_at) FROM offline_lead")
    suspend fun latestLeadSync(): Long?
}

@Dao
interface SyncStateDao {
    @Query("SELECT * FROM sync_cursor WHERE id = 'default' LIMIT 1")
    suspend fun current(): SyncCursorEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun save(entity: SyncCursorEntity)

    @Query("DELETE FROM sync_cursor")
    suspend fun clear()
}

@Dao
interface OutboxDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun save(entity: OutboxOperationEntity)

    @Query("SELECT * FROM outbox_operation WHERE status IN ('pending', 'retryable_error') ORDER BY created_at LIMIT :limit")
    suspend fun pending(limit: Int = 20): List<OutboxOperationEntity>

    @Query("SELECT * FROM outbox_operation ORDER BY updated_at DESC LIMIT :limit")
    suspend fun recent(limit: Int = 100): List<OutboxOperationEntity>

    @Query("SELECT * FROM outbox_operation WHERE operation_id = :operationId LIMIT 1")
    suspend fun find(operationId: String): OutboxOperationEntity?

    @Query("SELECT COUNT(*) FROM outbox_operation WHERE status = :status")
    suspend fun count(status: String): Int

    @Query("SELECT COUNT(*) FROM outbox_operation WHERE status IN ('pending', 'retryable_error', 'processing')")
    fun observePendingCount(): Flow<Int>

    @Query("DELETE FROM outbox_operation WHERE operation_id = :operationId AND status = 'pending'")
    suspend fun cancelPending(operationId: String): Int

    @Query("DELETE FROM outbox_operation")
    suspend fun deleteAll()
}

@Dao
interface ConflictDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun save(entity: SyncConflictEntity)

    @Query("SELECT * FROM sync_conflict WHERE status = 'open' ORDER BY created_at DESC")
    suspend fun open(): List<SyncConflictEntity>

    @Query("SELECT COUNT(*) FROM sync_conflict WHERE status = 'open'")
    fun observeOpenCount(): Flow<Int>

    @Query("UPDATE sync_conflict SET status = 'resolved', resolved_at = :resolvedAt WHERE operation_id = :operationId")
    suspend fun resolve(operationId: String, resolvedAt: Long = System.currentTimeMillis())

    @Query("DELETE FROM sync_conflict")
    suspend fun deleteAll()
}

@Dao
interface OfflineAttachmentDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun save(entity: OfflineAttachmentEntity)

    @Query("SELECT * FROM offline_attachment WHERE operation_id = :operationId ORDER BY created_at")
    suspend fun forOperation(operationId: String): List<OfflineAttachmentEntity>

    @Query("SELECT * FROM offline_attachment WHERE status IN ('pending', 'failed', 'uploading') ORDER BY created_at LIMIT :limit")
    suspend fun pending(limit: Int = 20): List<OfflineAttachmentEntity>

    @Query("UPDATE offline_attachment SET status = :status WHERE id = :id")
    suspend fun updateStatus(id: String, status: String)

    @Query("DELETE FROM offline_attachment WHERE id = :id")
    suspend fun delete(id: String)

    @Query("DELETE FROM offline_attachment WHERE operation_id = :operationId")
    suspend fun deleteForOperation(operationId: String)

    @Query("DELETE FROM offline_attachment")
    suspend fun deleteAll()
}
