package com.demo.management.core.error

import org.junit.Assert.assertEquals
import org.junit.Test

class ApiErrorMapperTest {
    @Test
    fun mapsKnownHttpStatusesToBusinessMessages() {
        assertEquals("登录已过期，请重新登录", ApiErrorMapper.fromStatus(401))
        assertEquals("当前账号没有此操作权限", ApiErrorMapper.fromStatus(403))
        assertEquals("提交内容有误，请检查必填项", ApiErrorMapper.fromStatus(422))
        assertEquals("服务暂时不可用，请稍后重试", ApiErrorMapper.fromStatus(500))
    }

    @Test
    fun prefersMobileBusinessMessageAndRequestId() {
        val json = """{"code":"validation_error","message":"日期格式错误","field_errors":[],"request_id":"req-123"}"""
        assertEquals("日期格式错误（编号 req-123）", ApiErrorMapper.fromPayload(json, 422))
    }
}
