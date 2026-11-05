package com.demo.management.core.auth

import com.demo.management.data.AuthApi
import com.demo.management.data.MobileRefreshRequest
import kotlinx.coroutines.runBlocking
import okhttp3.Authenticator
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route
import javax.inject.Inject

class RefreshAuthenticator @Inject constructor(
    private val authApi: AuthApi,
    private val sessionStore: SecureSessionStore,
    private val tokenProvider: TokenProvider,
) : Authenticator {
    override fun authenticate(route: Route?, response: Response): Request? = synchronized(this) {
        if (response.responseCount() >= 2) return@synchronized null
        val requestToken = response.request.header("Authorization")?.removePrefix("Bearer ")
        val currentToken = tokenProvider.accessToken()
        if (!currentToken.isNullOrBlank() && currentToken != requestToken) {
            return@synchronized response.request.newBuilder()
                .header("Authorization", "Bearer $currentToken")
                .build()
        }
        val refreshToken = tokenProvider.refreshToken() ?: sessionStore.refreshToken() ?: return@synchronized null
        val refreshed = runCatching {
            runBlocking {
                authApi.refresh(MobileRefreshRequest(refreshToken, sessionStore.deviceId()))
            }
        }.getOrNull() ?: run {
            sessionStore.clearTokens()
            tokenProvider.clear()
            return@synchronized null
        }
        sessionStore.save(refreshed.accessToken, refreshed.refreshToken)
        tokenProvider.update(refreshed.accessToken, refreshed.refreshToken)
        response.request.newBuilder()
            .header("Authorization", "Bearer ${refreshed.accessToken}")
            .build()
    }

    private fun Response.responseCount(): Int {
        var count = 1
        var current = priorResponse
        while (current != null) {
            count += 1
            current = current.priorResponse
        }
        return count
    }
}
