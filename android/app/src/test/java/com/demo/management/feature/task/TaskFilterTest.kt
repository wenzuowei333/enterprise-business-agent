package com.demo.management.feature.task

import com.demo.management.data.CrmTaskRow
import com.demo.management.data.ExecutionProject
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TaskFilterTest {
    @Test
    fun highFrequencyFiltersMapToBackendParameters() {
        assertEquals(true, "overdue".toFilter().overdue)
        assertEquals(true, "blocked".toFilter().blocked)
        assertEquals(true, "support".toFilter().needSupport)
        assertEquals("not_started", "not_started".toFilter().status)
        assertEquals(true, "closed".toFilter().closed)
    }

    @Test
    fun projectFiltersSeparateActiveOverdueAndClosedRows() {
        val active = project(id = 1, status = "active")
        val overdue = project(id = 2, status = "active", overdue = true)
        val closed = project(id = 3, status = "closed")
        val items = listOf(active, overdue, closed)

        assertEquals(listOf(1L, 2L), filterExecutionProjects(items, "", "active").map { it.id })
        assertEquals(listOf(2L), filterExecutionProjects(items, "", "overdue").map { it.id })
        assertEquals(listOf(3L), filterExecutionProjects(items, "", "closed").map { it.id })
        assertEquals(listOf(2L), filterExecutionProjects(items, "P-2", "all").map { it.id })
    }

    @Test
    fun taskFiltersSeparateSupportBlockedOverdueAndClosedRows() {
        val support = task(id = 1, needSupport = true)
        val blocked = task(id = 2, blocked = true)
        val overdue = task(id = 3, dueAt = "2020-08-31T07:59:59+08:00")
        val closed = task(id = 4, closed = true)
        val items = listOf(support, blocked, overdue, closed)

        assertEquals(listOf(1L), filterExecutionTasks(items, "", "support").map { it.id })
        assertEquals(listOf(2L), filterExecutionTasks(items, "", "blocked").map { it.id })
        assertEquals(listOf(3L), filterExecutionTasks(items, "", "overdue").map { it.id })
        assertEquals(listOf(4L), filterExecutionTasks(items, "", "closed").map { it.id })
        assertEquals(listOf(1L), filterExecutionTasks(items, "客户-1", "all").map { it.id })
    }

    @Test
    fun overdueComparisonUsesInstantAcrossTimeZones() {
        val now = Instant.parse("2026-08-31T00:00:00Z")

        assertTrue(isTaskOverdue(task(id = 1, dueAt = "2026-08-31T07:59:59+08:00"), now))
        assertFalse(isTaskOverdue(task(id = 2, dueAt = "2026-08-31T08:00:01+08:00"), now))
        assertFalse(isTaskOverdue(task(id = 3, dueAt = "invalid"), now))
    }

    private fun project(id: Long, status: String, overdue: Boolean = false) = ExecutionProject(
        id = id,
        projectCode = "P-$id",
        projectName = "项目-$id",
        status = status,
        overdue = overdue,
    )

    private fun task(
        id: Long,
        needSupport: Boolean = false,
        blocked: Boolean = false,
        closed: Boolean = false,
        dueAt: String? = null,
    ) = CrmTaskRow(
        id = id,
        projectId = 10,
        taskCode = "T-$id",
        customerCode = "C-$id",
        customerName = "客户-$id",
        feedbackDueAt = dueAt,
        status = if (closed) "closed" else "in_progress",
        needSupport = needSupport,
        isBlocked = blocked,
        isClosed = closed,
    )
}
