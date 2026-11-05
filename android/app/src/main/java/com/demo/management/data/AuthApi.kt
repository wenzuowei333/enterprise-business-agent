package com.demo.management.data

import retrofit2.http.Body
import retrofit2.http.POST

interface AuthApi {
    @POST("mobile/auth/login")
    suspend fun login(@Body request: MobileLoginRequest): MobileTokenResponse

    @POST("mobile/auth/refresh")
    suspend fun refresh(@Body request: MobileRefreshRequest): MobileTokenResponse

    @POST("mobile/auth/logout")
    suspend fun logout(@Body request: MobileRefreshRequest)
}
