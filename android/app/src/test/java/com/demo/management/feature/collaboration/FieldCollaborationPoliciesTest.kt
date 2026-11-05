package com.demo.management.feature.collaboration

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FieldCollaborationPoliciesTest {
    @Test
    fun customerTagsRequireFeatureAndRelevantPermission() {
        assertTrue(canViewCustomerTags(setOf("customer.view"), mapOf("customer_tags" to true)))
        assertFalse(canViewCustomerTags(setOf("customer.view"), mapOf("customer_tags" to false)))
        assertFalse(canViewCustomerTags(emptySet(), mapOf("customer_tags" to true)))
    }

    @Test
    fun fulfillmentSeparatesViewAndManagePermissions() {
        val flags = mapOf("fulfillment" to true)
        assertTrue(canViewFulfillment(setOf("delivery.view"), flags))
        assertFalse(canManageFulfillment(setOf("delivery.view"), flags))
        assertTrue(canManageFulfillment(setOf("delivery.view", "delivery.manage"), flags))
    }

    @Test
    fun deliveryTransitionsFollowServerStateMachine() {
        assertEquals(setOf("planned", "delivering", "cancelled"), deliveryTransitions("pending").map { it.toStatus }.toSet())
        assertEquals(setOf("delivered", "exception", "cancelled"), deliveryTransitions("delivering").map { it.toStatus }.toSet())
        assertTrue(deliveryTransitions("delivered").isEmpty())
        assertTrue(deliveryTransitions("cancelled").isEmpty())
    }

    @Test
    fun deliveryInputsMatchBusinessValidation() {
        val delivering = deliveryTransitions("delivering")
        assertTrue(delivering.first { it.toStatus == "delivered" }.requiresSignature)
        assertTrue(delivering.first { it.toStatus == "exception" }.requiresNote)
        assertTrue(delivering.first { it.toStatus == "cancelled" }.requiresNote)
    }
}
