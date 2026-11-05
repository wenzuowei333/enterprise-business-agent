package com.demo.management.core.voice

fun appendRecognizedText(current: String, recognized: String): String {
    val next = recognized.trim()
    if (next.isEmpty()) return current
    return listOf(current.trim(), next).filter { it.isNotEmpty() }.joinToString(" ")
}
