package com.demo.management.feature.customer

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Test

class ContactOcrParserTest {
    @Test
    fun parsesChineseBusinessCardIntoReviewCandidates() {
        val result = parseBusinessCardText(
            """
            星河演示商贸有限公司
            张三 销售经理
            手机：138 0013 8000
            微信：zhangsanwx
            地址：苏州市工业园区星湖街88号
            """.trimIndent()
        ).associateBy { it.field }

        assertEquals("星河演示商贸有限公司", result["customer_name"]?.value)
        assertEquals("张三", result["contact_name"]?.value)
        assertEquals("00000000000", result["contact_phone"]?.value)
        assertEquals("zhangsanwx", result["contact_channel"]?.value)
        assertEquals("苏州市工业园区星湖街88号", result["address"]?.value)
        assertFalse(result.values.any { it.selected })
    }

    @Test
    fun keepsMultiplePhonesForHumanReviewWithoutInventingAName() {
        val result = parseBusinessCardText("电话 0512-66668888\n手机 00000000000\n服务热线 400-800-9000")
        val phone = result.first { it.field == "contact_phone" }

        assertEquals("00000000000", phone.value)
        assertTrue(result.none { it.field == "contact_name" })
        assertTrue(phone.alternatives.contains("051266668888"))
    }
}
