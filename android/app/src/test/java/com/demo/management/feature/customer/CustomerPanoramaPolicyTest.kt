package com.demo.management.feature.customer

import com.demo.designsystem.components.StatusTone
import org.junit.Assert.assertEquals
import org.junit.Test

class CustomerPanoramaPolicyTest {
    @Test
    fun timelineUsesBusinessSemanticTones() {
        assertEquals(StatusTone.Danger, timelineTone("approval", "rejected"))
        assertEquals(StatusTone.Success, timelineTone("followup", "approved"))
        assertEquals(StatusTone.Warning, timelineTone("support", "open"))
        assertEquals(StatusTone.Info, timelineTone("task", "in_progress"))
    }

    @Test
    fun panoramaStatusLabelsAreChinese() {
        assertEquals("进行中", panoramaStatusLabel("in_progress"))
        assertEquals("待补充", panoramaStatusLabel("need_supplement"))
        assertEquals("已完成", panoramaStatusLabel("closed"))
    }
}
