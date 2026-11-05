package com.demo.management.feature.data

import java.time.LocalDate

data class DateRange(val from: String, val to: String)

fun dateRangeForPreset(preset: String, today: LocalDate = LocalDate.now()): DateRange? = when (preset) {
    "today" -> DateRange(today.toString(), today.toString())
    "yesterday" -> today.minusDays(1).let { DateRange(it.toString(), it.toString()) }
    "7d" -> DateRange(today.minusDays(6).toString(), today.toString())
    "month" -> DateRange(today.withDayOfMonth(1).toString(), today.toString())
    else -> null
}

fun optionalCheckDate(value: String): String? = value.trim().takeIf { it.isNotEmpty() }
