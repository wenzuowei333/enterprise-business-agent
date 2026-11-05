package com.demo.management.core.update

import java.io.ByteArrayInputStream
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ApkIntegrityPolicyTest {
    @Test
    fun acceptsExpectedSha256() {
        assertTrue(
            ApkIntegrityPolicy.matches(
                ByteArrayInputStream("hello".toByteArray()),
                "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            )
        )
    }

    @Test
    fun rejectsEmptyOrChangedHash() {
        assertFalse(ApkIntegrityPolicy.matches(ByteArrayInputStream("hello".toByteArray()), ""))
        assertFalse(ApkIntegrityPolicy.matches(ByteArrayInputStream("changed".toByteArray()), "2cf24dba"))
    }
}
