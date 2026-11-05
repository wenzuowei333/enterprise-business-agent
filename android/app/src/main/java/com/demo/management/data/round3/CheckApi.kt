package com.demo.management.data.round3

import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

interface CheckApi {
    @GET("mobile/checks/inventory/batches")
    suspend fun inventoryBatches(@Query("limit") limit: Int = 20, @Query("offset") offset: Int = 0): InventoryCheckBatchPage

    @Multipart
    @POST("mobile/checks/inventory/batches")
    suspend fun uploadInventory(@Part file: MultipartBody.Part, @Part("data_date") dataDate: RequestBody?): InventoryCheckBatch

    @GET("mobile/checks/inventory/batches/{batchId}/results")
    suspend fun inventoryResults(@Path("batchId") batchId: Long, @Query("type") type: String? = null, @Query("q") query: String? = null, @Query("limit") limit: Int = 20, @Query("offset") offset: Int = 0): RecordPage

    @Multipart
    @POST("mobile/checks/receivable/uploads")
    suspend fun uploadReceivable(@Part file: MultipartBody.Part, @Part("data_date") dataDate: RequestBody?): ImportBatch

    @POST("mobile/checks/receivable/uploads/{batchId}/validate")
    suspend fun validateReceivable(@Path("batchId") batchId: Long): ImportBatch

    @POST("mobile/checks/receivable/uploads/{batchId}/commit")
    suspend fun commitReceivable(@Path("batchId") batchId: Long): ImportBatch

    @GET("mobile/checks/receivable/results")
    suspend fun receivableResults(@Query("result_type") type: String? = null, @Query("q") query: String? = null, @Query("limit") limit: Int = 20, @Query("offset") offset: Int = 0): RecordPage
}
