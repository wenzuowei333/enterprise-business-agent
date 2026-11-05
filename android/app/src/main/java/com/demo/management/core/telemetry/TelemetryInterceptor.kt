package com.demo.management.core.telemetry

import okhttp3.Interceptor
import okhttp3.Response
import java.io.IOException
import javax.inject.Inject
import kotlin.math.min

class TelemetryInterceptor @Inject constructor(
    private val reporter: TelemetryReporter,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        if (request.url.encodedPath.endsWith("/mobile/telemetry/batch")) return chain.proceed(request)
        val started = System.nanoTime()
        return try {
            val response = chain.proceed(request)
            val duration = elapsedMs(started)
            reporter.recordApi(request.url.toString(), response.code, duration, response.header("X-Request-ID"))
            response
        } catch (error: IOException) {
            reporter.recordApi(request.url.toString(), null, elapsedMs(started), networkError = error.javaClass.simpleName)
            throw error
        }
    }

    private fun elapsedMs(started: Long): Int = min((System.nanoTime() - started) / 1_000_000L, 600_000L).toInt()

}
