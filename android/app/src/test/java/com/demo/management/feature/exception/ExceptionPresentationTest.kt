package com.demo.management.feature.exception

import org.junit.Assert.assertEquals
import org.junit.Test

class ExceptionPresentationTest {
    @Test
    fun serverCodesUseChineseBusinessLabels() {
        assertEquals("待处理", exceptionStatusLabel("open"))
        assertEquals("待行动", exceptionStatusLabel("action_required"))
        assertEquals("已阻塞", exceptionStatusLabel("blocked"))
        assertEquals("库存", exceptionDomainLabel("inventory"))
        assertEquals("主数据", exceptionDomainLabel("master_data"))
        assertEquals("CRM", exceptionDomainLabel("crm"))
        assertEquals("正在核对证据并生成结构化中文诊断", diagnosisProgressLabel("processing"))
        assertEquals("重新执行库存核验", actionLabel("rerun_inventory_check"))
    }
}
