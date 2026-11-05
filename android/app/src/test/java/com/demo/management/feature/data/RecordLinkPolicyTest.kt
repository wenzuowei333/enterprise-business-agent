package com.demo.management.feature.data

import org.junit.Assert.assertEquals
import org.junit.Test

class RecordLinkPolicyTest {
    @Test
    fun salesRecordLinksCustomerAndProduct() {
        val links = relatedRecordLinks(mapOf("customer_code" to "KH001", "product_code" to "P001"))
        assertEquals(listOf(DataRecordLink("customers", "KH001", "查看客户"), DataRecordLink("products", "P001", "查看商品")), links)
    }

    @Test
    fun purchaseRecordLinksSupplierAndProductWithoutBlankTargets() {
        val links = relatedRecordLinks(mapOf("supplier_code" to "G001", "product_code" to ""))
        assertEquals(listOf(DataRecordLink("suppliers", "G001", "查看供应商")), links)
    }
}
