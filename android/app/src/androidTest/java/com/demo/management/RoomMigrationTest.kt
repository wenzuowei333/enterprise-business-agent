package com.demo.management

import androidx.room.testing.MigrationTestHelper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.demo.management.core.network.DatabaseModule
import com.demo.management.data.local.AppDatabase
import net.zetetic.database.sqlcipher.SupportOpenHelperFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * This encrypted migration test is compile/package verified here; run it on an Android device or emulator.
 */
@RunWith(AndroidJUnit4::class)
class RoomMigrationTest {
    private val passphrase = "round6-migration-test-passphrase".encodeToByteArray()

    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        AppDatabase::class.java,
        emptyList(),
        SupportOpenHelperFactory(passphrase),
    )

    @Test
    fun migrateOneToTwoKeepsDrafts() {
        helper.createDatabase(TEST_DB, 1).apply {
            execSQL("INSERT INTO form_draft (draft_type, resource_id, content_json, updated_at) VALUES ('followup', '8', '{}', 1)")
            close()
        }
        helper.runMigrationsAndValidate(TEST_DB, 2, true, DatabaseModule.MIGRATION_1_2).use { database ->
            database.query("SELECT COUNT(*) FROM form_draft").use { cursor ->
                cursor.moveToFirst()
                assertEquals(1, cursor.getInt(0))
            }
            database.query("SELECT COUNT(*) FROM offline_customer").use { cursor ->
                cursor.moveToFirst()
                assertEquals(0, cursor.getInt(0))
            }
        }
    }

    @Test
    fun migrateTwoToThreeKeepsCachedDataAndCreatesLeadCache() {
        helper.createDatabase(ROUND_SIX_DB, 2).apply {
            execSQL("INSERT INTO offline_customer (customer_code, customer_name, payload_json, synced_at) VALUES ('C-1', '杭州客户', '{}', 1)")
            execSQL("INSERT INTO form_draft (draft_type, resource_id, content_json, updated_at) VALUES ('crm_lead_new', 'draft-1', '{}', 1)")
            close()
        }
        assertFalse(isPlaintextDatabase(ROUND_SIX_DB))

        helper.runMigrationsAndValidate(ROUND_SIX_DB, 3, true, DatabaseModule.MIGRATION_2_3).use { database ->
            database.query("SELECT customer_name FROM offline_customer WHERE customer_code = 'C-1'").use { cursor ->
                cursor.moveToFirst()
                assertEquals("杭州客户", cursor.getString(0))
            }
            database.query("SELECT COUNT(*) FROM form_draft WHERE draft_type = 'crm_lead_new'").use { cursor ->
                cursor.moveToFirst()
                assertEquals(1, cursor.getInt(0))
            }
            database.query("SELECT COUNT(*) FROM offline_lead").use { cursor ->
                cursor.moveToFirst()
                assertEquals(0, cursor.getInt(0))
            }
        }
    }

    @Test
    fun migrateThreeToFourDropsLegacyLeadRowsOutsidePrivateCacheScope() {
        helper.createDatabase(ROUND_SEVEN_DB, 3).apply {
            execSQL("INSERT INTO offline_lead (id, lead_name, status, payload_json, synced_at) VALUES (7, '旧缓存线索', 'active', '{}', 1)")
            close()
        }

        helper.runMigrationsAndValidate(ROUND_SEVEN_DB, 4, true, DatabaseModule.MIGRATION_3_4).use { database ->
            database.query("SELECT COUNT(*) FROM offline_lead").use { cursor ->
                cursor.moveToFirst()
                assertEquals(0, cursor.getInt(0))
            }
        }
    }

    private companion object {
        init { System.loadLibrary("sqlcipher") }

        const val TEST_DB = "round4-migration-test"
        const val ROUND_SIX_DB = "round6-migration-test"
        const val ROUND_SEVEN_DB = "round7-migration-test"
    }

    private fun isPlaintextDatabase(name: String): Boolean {
        val header = ByteArray(16)
        InstrumentationRegistry.getInstrumentation().targetContext.getDatabasePath(name).inputStream().use { input ->
            return input.read(header) == header.size && header.decodeToString() == "SQLite format 3\u0000"
        }
    }
}
