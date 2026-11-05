package com.demo.management.feature.task

import com.demo.management.data.CrmProjectSummary
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TaskProjectPurposeTest {
    private val adapter = Moshi.Builder()
        .addLast(KotlinJsonAdapterFactory())
        .build()
        .adapter(CrmProjectSummary::class.java)

    @Test
    fun projectPurposeIsParsedFromTaskDetailProject() {
        val project = adapter.fromJson(
            """{"id":11,"project_code":"CRMP001","project_name":"客户拜访","status":"active","purpose":"收集客户基本资料和经营资料"}"""
        )

        assertEquals("收集客户基本资料和经营资料", project?.purpose)
    }

    @Test
    fun missingPurposeRemainsBackwardCompatible() {
        val project = adapter.fromJson(
            """{"id":11,"project_code":"CRMP001","project_name":"客户拜访","status":"active"}"""
        )

        assertNull(project?.purpose)
        assertEquals("未填写", taskProjectPurposeText(project?.purpose))
        assertEquals("未填写", taskProjectPurposeText("  "))
    }

    @Test
    fun longPurposeIsNotTruncatedBeforeRendering() {
        val purpose = "本次项目需要完成客户基础资料、经营资料、跟进事实和后续协同动作的完整收集"

        assertEquals(purpose, taskProjectPurposeText(purpose))
    }
}
