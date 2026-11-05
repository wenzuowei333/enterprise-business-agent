package com.demo.management.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface FormDraftDao {
    @Query("SELECT * FROM form_draft WHERE draft_type = :type AND resource_id = :resourceId LIMIT 1")
    suspend fun find(type: String, resourceId: String): FormDraftEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun save(entity: FormDraftEntity)

    @Query("DELETE FROM form_draft WHERE draft_type = :type AND resource_id = :resourceId")
    suspend fun delete(type: String, resourceId: String)

    @Query("SELECT COUNT(*) FROM form_draft")
    suspend fun count(): Int

    @Query("DELETE FROM form_draft")
    suspend fun deleteAll()
}
