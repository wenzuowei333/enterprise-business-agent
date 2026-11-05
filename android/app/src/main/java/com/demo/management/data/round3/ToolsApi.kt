package com.demo.management.data.round3

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface ToolsApi {
    @GET("mobile/notifications")
    suspend fun notifications(): NotificationCenter

    @POST("mobile/notifications/{id}/process")
    suspend fun processNotification(@Path("id") id: String, @Body payload: NotificationActionRequest): Map<String, Any?>

    @GET("mobile/scan/resolve")
    suspend fun resolveScan(@Query("value") value: String): ScanResult

    @POST("mobile/telemetry/batch")
    suspend fun telemetry(@Body payload: TelemetryBatch): Map<String, Int>

    @GET("mobile/dashboard/overview")
    suspend fun dashboard(@Query("range") range: String = "7d"): DashboardOverview

    @GET("mobile/assistant/runtime")
    suspend fun assistantRuntime(): AssistantRuntime

    @GET("mobile/assistant/messages")
    suspend fun assistantMessages(@Query("limit") limit: Int = 30): List<Map<String, Any?>>

    @POST("mobile/assistant/messages")
    suspend fun sendAssistantMessage(@Body payload: AssistantMessageRequest): AssistantMessageResponse
}
