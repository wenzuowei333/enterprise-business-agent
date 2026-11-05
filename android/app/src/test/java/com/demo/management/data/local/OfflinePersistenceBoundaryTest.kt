package com.demo.management.data.local

import com.squareup.moshi.Moshi
import org.junit.Assert.assertEquals
import org.junit.Test

class OfflinePersistenceBoundaryTest {
    @Test
    fun roomSchemaContainsOnlyTheApprovedOfflineEntities() {
        val schema = checkNotNull(javaClass.getResourceAsStream("/com.demo.management.data.local.AppDatabase/4.json"))
            .bufferedReader()
            .use { it.readText() }
        val root = checkNotNull(Moshi.Builder().build().adapter(Map::class.java).fromJson(schema))
        val database = root["database"] as Map<*, *>
        val entities = database["entities"] as List<*>
        val tables = entities
            .map { (it as Map<*, *>)["tableName"] as String }
            .toSet()

        assertEquals(
            setOf(
                "project_draft",
                "form_draft",
                "offline_customer",
                "offline_task",
                "offline_lead",
                "offline_dictionary",
                "sync_cursor",
                "outbox_operation",
                "sync_conflict",
                "offline_attachment",
            ),
            tables,
        )
    }
}
