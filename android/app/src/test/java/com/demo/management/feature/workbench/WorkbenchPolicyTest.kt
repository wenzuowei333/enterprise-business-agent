package com.demo.management.feature.workbench

import com.demo.designsystem.components.StatusTone
import com.demo.management.data.WorkbenchTarget
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WorkbenchPolicyTest {
    @Test
    fun queueToneUsesSemanticStatusColors() {
        assertEquals(StatusTone.Danger, "bad".toStatusTone())
        assertEquals(StatusTone.Warning, "warn".toStatusTone())
        assertEquals(StatusTone.Success, "good".toStatusTone())
        assertEquals(StatusTone.Neutral, "unknown".toStatusTone())
    }

    @Test
    fun workbenchTargetsStayInsideAuthorizedBusinessRoutes() {
        assertEquals("projects", workbenchRoute(WorkbenchTarget(page = "tasks", taskId = 9)))
        assertEquals("approvals", workbenchRoute(WorkbenchTarget(page = "approvals", approvalId = 3)))
        assertEquals("work_items", workbenchRoute(WorkbenchTarget(page = "work_items", workItemId = 5)))
        assertNull(workbenchRoute(WorkbenchTarget(page = "external")))
    }
}
