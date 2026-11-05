package com.demo.management.feature.customer

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CustomerProfileDiffTest {
    private val original = CustomerProfileForm(
        customerName = "测试客户",
        contactPhone = "00000000000",
        customerGroupName = "旧群",
        address = "苏州",
    )

    @Test
    fun onlyChangedFieldIsSubmitted() {
        val changes = customerProfileChanges(original.copy(customerGroupName = "新群"), original)

        assertEquals(mapOf("customer_group_name" to "新群"), changes)
        assertFalse(changes.containsKey("contact_phone"))
    }

    @Test
    fun explicitClearIsRepresentedByNull() {
        val changes = customerProfileChanges(original.copy(contactPhone = ""), original)

        assertEquals(true, changes.containsKey("contact_phone"))
        assertNull(changes["contact_phone"])
    }

    @Test
    fun ocrOnlyReplacesConfirmedFields() {
        val merged = applyOcrProfileValues(
            original,
            mapOf("contact_phone" to "00000000000", "contact_name" to "新联系人"),
        )

        assertEquals("00000000000", merged.contactPhone)
        assertEquals("新联系人", merged.contactName)
        assertEquals(original.customerGroupName, merged.customerGroupName)
        assertEquals(original.region, merged.region)
    }

    @Test
    fun ocrCandidatesAreUnselectedByDefault() {
        val candidates = parseBusinessCardText("测试食品有限公司\n张三\n电话 00000000000")

        assertTrue(candidates.isNotEmpty())
        assertTrue(candidates.all { !it.selected })
    }

    @Test
    fun existingValuesRequireExplicitOverwriteConfirmation() {
        val conflicts = ocrOverwriteFields(
            currentValues = mapOf("contact_phone" to "00000000000", "contact_name" to ""),
            selectedValues = mapOf("contact_phone" to "00000000000", "contact_name" to "张三"),
        )

        assertEquals(setOf("contact_phone"), conflicts)
    }
}
