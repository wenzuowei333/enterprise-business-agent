package com.demo.management.core.network

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.demo.management.core.auth.SecureSessionStore
import com.demo.management.data.local.AppDatabase
import com.demo.management.data.local.ConflictDao
import com.demo.management.data.local.FormDraftDao
import com.demo.management.data.local.FormDraftEntity
import com.demo.management.data.local.OfflineAttachmentDao
import com.demo.management.data.local.OfflineDao
import com.demo.management.data.local.OutboxDao
import com.demo.management.data.local.ProjectDraftDao
import com.demo.management.data.local.ProjectDraftEntity
import com.demo.management.data.local.SyncStateDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.runBlocking
import net.zetetic.database.sqlcipher.SupportOpenHelperFactory
import java.io.FileInputStream
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {
    private const val DATABASE_NAME = "demo-mobile.db"

    @Provides
    @Singleton
    fun provideDatabase(
        @ApplicationContext context: Context,
        sessionStore: SecureSessionStore,
    ): AppDatabase {
        if (sessionStore.consumeDatabaseKeyRotation()) context.deleteDatabase(DATABASE_NAME)
        val backup = backupPlaintextDrafts(context)
        if (backup != null) context.deleteDatabase(DATABASE_NAME)
        System.loadLibrary("sqlcipher")
        val database = Room.databaseBuilder(context, AppDatabase::class.java, DATABASE_NAME)
            .openHelperFactory(SupportOpenHelperFactory(sessionStore.databasePassphrase()))
            .addMigrations(MIGRATION_1_2)
            .addMigrations(MIGRATION_2_3)
            .addMigrations(MIGRATION_3_4)
            .build()
        if (backup != null) {
            runBlocking {
                for (draft in backup.projects) database.projectDraftDao().save(draft)
                for (draft in backup.forms) database.formDraftDao().save(draft)
            }
        }
        return database
    }

    @Provides fun provideProjectDraftDao(database: AppDatabase): ProjectDraftDao = database.projectDraftDao()
    @Provides fun provideFormDraftDao(database: AppDatabase): FormDraftDao = database.formDraftDao()
    @Provides fun provideOfflineDao(database: AppDatabase): OfflineDao = database.offlineDao()
    @Provides fun provideSyncStateDao(database: AppDatabase): SyncStateDao = database.syncStateDao()
    @Provides fun provideOutboxDao(database: AppDatabase): OutboxDao = database.outboxDao()
    @Provides fun provideConflictDao(database: AppDatabase): ConflictDao = database.conflictDao()
    @Provides fun provideOfflineAttachmentDao(database: AppDatabase): OfflineAttachmentDao = database.offlineAttachmentDao()

    private fun backupPlaintextDrafts(context: Context): LegacyDraftBackup? {
        val file = context.getDatabasePath(DATABASE_NAME)
        if (!file.exists() || !hasPlaintextHeader(file.path)) return null
        val projects = mutableListOf<ProjectDraftEntity>()
        val forms = mutableListOf<FormDraftEntity>()
        val database = SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY)
        database.rawQuery("SELECT id, approval_id, content_json, updated_at FROM project_draft", null).use { cursor ->
            while (cursor.moveToNext()) {
                projects += ProjectDraftEntity(
                    id = cursor.getString(0),
                    approvalId = cursor.takeUnless { it.isNull(1) }?.getLong(1),
                    contentJson = cursor.getString(2),
                    updatedAt = cursor.getLong(3),
                )
            }
        }
        database.rawQuery("SELECT draft_type, resource_id, content_json, updated_at FROM form_draft", null).use { cursor ->
            while (cursor.moveToNext()) {
                forms += FormDraftEntity(
                    draftType = cursor.getString(0),
                    resourceId = cursor.getString(1),
                    contentJson = cursor.getString(2),
                    updatedAt = cursor.getLong(3),
                )
            }
        }
        database.close()
        return LegacyDraftBackup(projects, forms)
    }

    private fun hasPlaintextHeader(path: String): Boolean = runCatching {
        FileInputStream(path).use { input ->
            val header = ByteArray(16)
            input.read(header) == header.size && header.decodeToString() == "SQLite format 3\u0000"
        }
    }.getOrDefault(false)

    private data class LegacyDraftBackup(
        val projects: List<ProjectDraftEntity>,
        val forms: List<FormDraftEntity>,
    )

    val MIGRATION_1_2 = object : Migration(1, 2) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL("CREATE TABLE IF NOT EXISTS `offline_customer` (`customer_code` TEXT NOT NULL, `customer_name` TEXT NOT NULL, `payload_json` TEXT NOT NULL, `remote_updated_at` TEXT, `synced_at` INTEGER NOT NULL, PRIMARY KEY(`customer_code`))")
            db.execSQL("CREATE TABLE IF NOT EXISTS `offline_task` (`id` INTEGER NOT NULL, `customer_code` TEXT NOT NULL, `status` TEXT NOT NULL, `payload_json` TEXT NOT NULL, `remote_updated_at` TEXT, `synced_at` INTEGER NOT NULL, PRIMARY KEY(`id`))")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_offline_task_customer_code` ON `offline_task` (`customer_code`)")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_offline_task_status` ON `offline_task` (`status`)")
            db.execSQL("CREATE TABLE IF NOT EXISTS `offline_dictionary` (`dictionary_key` TEXT NOT NULL, `payload_json` TEXT NOT NULL, `synced_at` INTEGER NOT NULL, PRIMARY KEY(`dictionary_key`))")
            db.execSQL("CREATE TABLE IF NOT EXISTS `sync_cursor` (`id` TEXT NOT NULL, `cursor` TEXT, `scope_revision` TEXT, `last_synced_at` INTEGER, `last_error` TEXT, PRIMARY KEY(`id`))")
            db.execSQL("CREATE TABLE IF NOT EXISTS `outbox_operation` (`operation_id` TEXT NOT NULL, `action_type` TEXT NOT NULL, `resource_type` TEXT, `resource_id` TEXT, `base_updated_at` TEXT, `payload_json` TEXT NOT NULL, `attachments_json` TEXT NOT NULL, `status` TEXT NOT NULL, `attempt_count` INTEGER NOT NULL, `error_code` TEXT, `error_message` TEXT, `created_at` INTEGER NOT NULL, `updated_at` INTEGER NOT NULL, PRIMARY KEY(`operation_id`))")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_outbox_operation_status` ON `outbox_operation` (`status`)")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_outbox_operation_resource_type_resource_id` ON `outbox_operation` (`resource_type`, `resource_id`)")
            db.execSQL("CREATE TABLE IF NOT EXISTS `sync_conflict` (`operation_id` TEXT NOT NULL, `resource_type` TEXT, `resource_id` TEXT, `conflict_json` TEXT NOT NULL, `status` TEXT NOT NULL, `created_at` INTEGER NOT NULL, `resolved_at` INTEGER, PRIMARY KEY(`operation_id`))")
            db.execSQL("CREATE TABLE IF NOT EXISTS `offline_attachment` (`id` TEXT NOT NULL, `operation_id` TEXT NOT NULL, `encrypted_path` TEXT NOT NULL, `display_name` TEXT NOT NULL, `mime_type` TEXT, `size_bytes` INTEGER NOT NULL, `status` TEXT NOT NULL, `created_at` INTEGER NOT NULL, PRIMARY KEY(`id`))")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_offline_attachment_operation_id` ON `offline_attachment` (`operation_id`)")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_offline_attachment_status` ON `offline_attachment` (`status`)")
        }
    }

    val MIGRATION_2_3 = object : Migration(2, 3) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL("CREATE TABLE IF NOT EXISTS `offline_lead` (`id` INTEGER NOT NULL, `lead_name` TEXT NOT NULL, `status` TEXT NOT NULL, `payload_json` TEXT NOT NULL, `remote_updated_at` TEXT, `synced_at` INTEGER NOT NULL, PRIMARY KEY(`id`))")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_offline_lead_status` ON `offline_lead` (`status`)")
        }
    }

    val MIGRATION_3_4 = object : Migration(3, 4) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL("ALTER TABLE `offline_lead` ADD COLUMN `cache_scope` TEXT NOT NULL DEFAULT 'legacy'")
            // Version 3 did not record ownership. Clear it rather than risking public-pool or out-of-scope PII offline.
            db.execSQL("DELETE FROM `offline_lead` WHERE `cache_scope` NOT IN ('owned', 'assigned')")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_offline_lead_cache_scope` ON `offline_lead` (`cache_scope`)")
        }
    }
}
