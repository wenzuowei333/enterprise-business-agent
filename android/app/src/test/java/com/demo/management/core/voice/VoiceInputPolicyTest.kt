package com.demo.management.core.voice

import org.junit.Assert.assertEquals
import org.junit.Test

class VoiceInputPolicyTest {
    @Test
    fun recognizedTextAppendsWithoutDestroyingExistingInput() {
        assertEquals("已沟通价格 客户要求周五回复", appendRecognizedText("已沟通价格", " 客户要求周五回复 "))
    }

    @Test
    fun blankRecognitionLeavesInputUntouched() {
        assertEquals("原内容", appendRecognizedText("原内容", "   "))
    }
}
