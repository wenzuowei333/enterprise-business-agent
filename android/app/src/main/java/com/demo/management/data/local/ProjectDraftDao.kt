package com.demo.management.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface ProjectDraftDao {
    @Query("SELECT * FROM project_draft WHERE id = :id LIMIT 1")
    suspend fun find(id: String = "current"): ProjectDraftEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun save(entity: ProjectDraftEntity)

    @Query("DELETE FROM project_draft WHERE id = :id")
    suspend fun delete(id: String = "current")

    @Query("SELECT COUNT(*) FROM project_draft")
    suspend fun count(): Int

    @Query("DELETE FROM project_draft")
    suspend fun deleteAll()
}
