package com.demo.management.core.update

import java.io.InputStream
import java.security.MessageDigest

object ApkIntegrityPolicy {
    fun sha256(input: InputStream): String {
        val digest = MessageDigest.getInstance("SHA-256")
        input.buffered().use { stream ->
            val buffer = ByteArray(8192)
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    fun matches(input: InputStream, expected: String): Boolean =
        expected.isNotBlank() && sha256(input).equals(expected.trim(), ignoreCase = true)
}
