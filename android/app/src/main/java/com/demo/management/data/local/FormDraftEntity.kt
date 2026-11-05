package com.demo.management.data.local

import androidx.room.ColumnInfo
import androidx.room.Entity

@Entity(tableName = "form_draft", primaryKeys = ["draft_type", "resource_id"])
data class FormDraftEntity(
    @ColumnInfo(name = "draft_type") val draftType: String,
    @ColumnInfo(name = "resource_id") val resourceId: String,
    @ColumnInfo(name = "content_json") val contentJson: String,
    @ColumnInfo(name = "updated_at") val updatedAt: Long = System.currentTimeMillis(),
)
