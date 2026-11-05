package com.demo.management.feature.projectApplication

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ProjectPayloadTest {
    @Test
    fun payloadKeepsFlowRolesAndPerCustomerExecutor() {
        val request = ProjectApplicationSnapshot(
            projectName = "客户拜访",
            landingApproverUserId = 1,
            ownerUserId = 2,
            frontlineUserIds = listOf(3, 4),
            progressCcUserIds = listOf(5),
            customers = listOf(SelectedProjectCustomer("KH001", "客户一", executorUserId = 4, executorEmployeeCode = "E004")),
        ).toRequest(submit = true)

        assertEquals(1L, request.project.landingApproverUserId)
        assertEquals(2L, request.project.ownerUserId)
        assertEquals(listOf(3L, 4L), request.project.participantUserIds)
        assertEquals(listOf(5L), request.project.progressCcUserIds)
        assertEquals(4L, request.tasks.single().executorUserId)
        assertTrue(request.submit)
    }
}
