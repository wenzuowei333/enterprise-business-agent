package com.demo.management.data.round3

import retrofit2.http.GET
import retrofit2.http.Path
import retrofit2.http.Query

interface DataApi {
    @GET("mobile/data/overview")
    suspend fun overview(): DataOverview

    @GET("mobile/data/master/{kind}")
    suspend fun master(
        @Path("kind") kind: String,
        @Query("q") query: String? = null,
        @Query("limit") limit: Int = 20,
        @Query("offset") offset: Int = 0,
    ): RecordPage

    @GET("mobile/data/sales")
    suspend fun sales(@Query("q") query: String? = null, @Query("date_from") dateFrom: String? = null, @Query("date_to") dateTo: String? = null, @Query("warehouse_name") warehouse: String? = null, @Query("limit") limit: Int = 20, @Query("offset") offset: Int = 0): RecordPage

    @GET("mobile/data/purchases")
    suspend fun purchases(@Query("q") query: String? = null, @Query("date_from") dateFrom: String? = null, @Query("date_to") dateTo: String? = null, @Query("warehouse_name") warehouse: String? = null, @Query("limit") limit: Int = 20, @Query("offset") offset: Int = 0): RecordPage

    @GET("mobile/data/account-ledger")
    suspend fun accountLedger(@Query("q") query: String? = null, @Query("date_from") dateFrom: String? = null, @Query("date_to") dateTo: String? = null, @Query("limit") limit: Int = 20, @Query("offset") offset: Int = 0): RecordPage

    @GET("mobile/data/inventory-snapshots")
    suspend fun inventory(@Query("q") query: String? = null, @Query("date_from") dateFrom: String? = null, @Query("date_to") dateTo: String? = null, @Query("warehouse_name") warehouse: String? = null, @Query("inventory_status") status: String? = null, @Query("limit") limit: Int = 20, @Query("offset") offset: Int = 0): RecordPage
}
