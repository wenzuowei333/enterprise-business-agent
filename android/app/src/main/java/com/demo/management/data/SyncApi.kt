package com.demo.management.data

import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface SyncApi {
    @GET("mobile/sync/pull")
    suspend fun pull(
        @Query("cursor") cursor: String? = null,
        @Query("scope_revision") scopeRevision: String? = null,
        @Query("device_id") deviceId: String? = null,
    ): SyncPullPayload

    @POST("mobile/sync/operations")
    suspend fun operations(@Body payload: SyncOperationBatch): SyncOperationBatchResult

    @GET("mobile/sync/status")
    suspend fun status(@Query("device_id") deviceId: String? = null): SyncStatusPayload

    @GET("mobile/devices")
    suspend fun devices(@Query("current_device_id") currentDeviceId: String): MobileDevicePage

    @DELETE("mobile/devices/{sessionId}")
    suspend fun revokeDevice(@Path("sessionId") sessionId: Long): Map<String, Any?>

    @PATCH("mobile/devices/{sessionId}/notifications")
    suspend fun updateNotifications(
        @Path("sessionId") sessionId: Long,
        @Body payload: NotificationPreferencesUpdate,
    ): MobileDevice
}
