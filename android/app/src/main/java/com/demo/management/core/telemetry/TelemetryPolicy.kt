package com.demo.management.core.telemetry

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

fun sanitizedTelemetryRoute(url: String): String = url.toHttpUrlOrNull()?.encodedPath
    ?: url.substringBefore('?').substringAfter("://", missingDelimiterValue = url)
