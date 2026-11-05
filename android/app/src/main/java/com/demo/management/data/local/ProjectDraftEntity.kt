package com.demo.management.data.local

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "project_draft")
data class ProjectDraftEntity(
    @PrimaryKey val id: String = "current",
    @ColumnInfo(name = "approval_id") val approvalId: Long? = null,
    @ColumnInfo(name = "content_json") val contentJson: String,
    @ColumnInfo(name = "updated_at") val updatedAt: Long = System.currentTimeMillis(),
)
