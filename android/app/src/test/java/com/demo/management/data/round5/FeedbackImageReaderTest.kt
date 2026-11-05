package com.demo.management.data.round5

import java.io.ByteArrayInputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class FeedbackImageReaderTest {
    @Test
    fun detectsImageTypeFromSignatureInsteadOfProviderMetadata() {
        val image = readFeedbackImage(ByteArrayInputStream(byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)))

        assertEquals("image/png", image.contentType)
        assertEquals("png", image.extension)
    }

    @Test
    fun stopsReadingWhenScreenshotExceedsFiveMegabytes() {
        assertThrows(IllegalArgumentException::class.java) {
            readFeedbackImage(ByteArrayInputStream(ByteArray(5 * 1024 * 1024 + 1)))
        }
    }

    @Test
    fun rejectsUnknownImageSignature() {
        assertThrows(IllegalArgumentException::class.java) {
            readFeedbackImage(ByteArrayInputStream("not-an-image".encodeToByteArray()))
        }
    }
}
