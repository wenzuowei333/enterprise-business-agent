package com.demo.management.data.round5

import okhttp3.MultipartBody
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

interface Round5Api {
    @POST("mobile/feedback")
    suspend fun createFeedback(@Body payload: FeedbackCreate): FeedbackRow

    @GET("mobile/feedback/mine")
    suspend fun myFeedback(@Query("limit") limit: Int = 20, @Query("offset") offset: Int = 0): FeedbackPage

    @Multipart
    @POST("mobile/feedback/attachments")
    suspend fun uploadFeedbackAttachment(@Part file: MultipartBody.Part): FeedbackAttachment

    @GET("mobile/admin/feedback")
    suspend fun adminFeedback(@Query("status") status: String? = null, @Query("limit") limit: Int = 50): FeedbackPage

    @PATCH("mobile/admin/feedback/{id}")
    suspend fun updateFeedback(@Path("id") id: Long, @Body payload: FeedbackUpdate): FeedbackRow

    @POST("mobile/assistant/drafts/followup")
    suspend fun followupDraft(@Body payload: AssistantDraftRequest): AssistantDraftResponse

    @POST("mobile/assistant/drafts/approval-opinion")
    suspend fun approvalOpinionDraft(@Body payload: AssistantDraftRequest): AssistantDraftResponse

    @POST("mobile/assistant/drafts/project-summary")
    suspend fun projectSummaryDraft(@Body payload: AssistantDraftRequest): AssistantDraftResponse

    @GET("mobile/admin/adoption/overview")
    suspend fun adoptionOverview(@Query("days") days: Int = 7): AdoptionOverview
}
