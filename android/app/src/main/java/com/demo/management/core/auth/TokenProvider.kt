package com.demo.management.core.auth

interface TokenProvider {
    fun accessToken(): String?
    fun refreshToken(): String?
    fun update(accessToken: String, refreshToken: String)
    fun clear()
}

fun hydrateTokenProvider(accessToken: String?, refreshToken: String?, provider: TokenProvider): Boolean {
    if (accessToken.isNullOrBlank() || refreshToken.isNullOrBlank()) return false
    provider.update(accessToken, refreshToken)
    return true
}

class InMemoryTokenProvider : TokenProvider {
    @Volatile
    private var access: String? = null

    @Volatile
    private var refresh: String? = null

    override fun accessToken(): String? = access

    override fun refreshToken(): String? = refresh

    override fun update(accessToken: String, refreshToken: String) {
        access = accessToken
        refresh = refreshToken
    }

    override fun clear() {
        access = null
        refresh = null
    }
}
