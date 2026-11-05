package com.demo.management.data.round6

import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface Round6Api {
    @GET("mobile/leads")
    suspend fun leads(
        @Query("q") query: String? = null,
        @Query("status") status: String? = null,
        @Query("source") source: String? = null,
        @Query("region") region: String? = null,
        @Query("assigned_user_id") assignedUserId: Long? = null,
        @Query("limit") limit: Int = 20,
        @Query("offset") offset: Int = 0,
    ): LeadPage

    @GET("mobile/leads/{leadId}")
    suspend fun lead(@Path("leadId") leadId: Long): LeadRow

    @GET("mobile/leads/public-pool")
    suspend fun publicPool(
        @Query("q") query: String? = null,
        @Query("source") source: String? = null,
        @Query("region") region: String? = null,
        @Query("priority") priority: String? = null,
        @Query("limit") limit: Int = 20,
        @Query("offset") offset: Int = 0,
    ): LeadPublicPoolPage

    @GET("mobile/leads/sla-exceptions")
    suspend fun slaExceptions(
        @Query("state") state: String? = null,
        @Query("today_only") todayOnly: Boolean = false,
        @Query("limit") limit: Int = 20,
        @Query("offset") offset: Int = 0,
    ): LeadSlaExceptionPage

    @POST("mobile/leads")
    suspend fun createLead(@Body payload: LeadCreate): LeadRow

    @PATCH("mobile/leads/{leadId}")
    suspend fun updateLead(@Path("leadId") leadId: Long, @Body payload: LeadUpdate): LeadRow

    @DELETE("mobile/leads/{leadId}")
    suspend fun closeLead(@Path("leadId") leadId: Long): Map<String, Any?>

    @POST("mobile/leads/{leadId}/assign")
    suspend fun assignLead(@Path("leadId") leadId: Long, @Body payload: LeadAssignmentRequest): LeadRow

    @POST("mobile/leads/{leadId}/claim")
    suspend fun claimLead(@Path("leadId") leadId: Long): LeadRow

    @POST("mobile/leads/{leadId}/recycle")
    suspend fun recycleLead(@Path("leadId") leadId: Long, @Body payload: LeadRecycleRequest): LeadRow

    @POST("mobile/leads/{leadId}/conversion-approval-draft")
    suspend fun createConversionApproval(
        @Path("leadId") leadId: Long,
        @Body payload: LeadConversionApprovalRequest,
    ): Map<String, Any?>

    @GET("mobile/leads/{leadId}/project-prefill")
    suspend fun projectPrefill(@Path("leadId") leadId: Long): LeadProjectPrefill

    @GET("mobile/leads/duplicate-check")
    suspend fun duplicateCheck(
        @Query("lead_name") leadName: String? = null,
        @Query("contact_phone") contactPhone: String? = null,
        @Query("exclude_lead_id") excludeLeadId: Long? = null,
    ): Map<String, Any?>

    @GET("mobile/leads/summary")
    suspend fun summary(): Map<String, Any?>

    @GET("mobile/leads/dimensions")
    suspend fun dimensions(): Map<String, Any?>

    @GET("mobile/leads/analytics")
    suspend fun analytics(): Map<String, Any?>
}
