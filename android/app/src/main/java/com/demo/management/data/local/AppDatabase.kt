package com.demo.management.data.local

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [
        ProjectDraftEntity::class,
        FormDraftEntity::class,
        OfflineCustomerEntity::class,
        OfflineTaskEntity::class,
        OfflineLeadEntity::class,
        OfflineDictionaryEntity::class,
        SyncCursorEntity::class,
        OutboxOperationEntity::class,
        SyncConflictEntity::class,
        OfflineAttachmentEntity::class,
    ],
    version = 4,
    exportSchema = true,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun projectDraftDao(): ProjectDraftDao
    abstract fun formDraftDao(): FormDraftDao
    abstract fun offlineDao(): OfflineDao
    abstract fun syncStateDao(): SyncStateDao
    abstract fun outboxDao(): OutboxDao
    abstract fun conflictDao(): ConflictDao
    abstract fun offlineAttachmentDao(): OfflineAttachmentDao
}
