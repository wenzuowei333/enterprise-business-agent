package com.demo.management.core.auth

import android.annotation.SuppressLint
import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.UUID
import java.security.SecureRandom
import android.util.Base64
import javax.inject.Inject
import javax.inject.Singleton
import com.demo.management.core.onboarding.onboardingCompletionKey

@Singleton
class SecureSessionStore @Inject constructor(@ApplicationContext context: Context) {
    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()
    private val preferences = EncryptedSharedPreferences.create(
        context,
        "secure_mobile_session",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun accessToken(): String? = preferences.getString(KEY_ACCESS_TOKEN, null)

    fun refreshToken(): String? = preferences.getString(KEY_REFRESH_TOKEN, null)

    fun deviceId(): String {
        val existing = preferences.getString(KEY_DEVICE_ID, null)
        if (!existing.isNullOrBlank()) return existing
        return UUID.randomUUID().toString().also {
            preferences.edit().putString(KEY_DEVICE_ID, it).apply()
        }
    }

    fun save(accessToken: String, refreshToken: String) {
        preferences.edit()
            .putString(KEY_ACCESS_TOKEN, accessToken)
            .putString(KEY_REFRESH_TOKEN, refreshToken)
            .apply()
    }

    fun saveBootstrap(value: String) {
        preferences.edit().putString(KEY_BOOTSTRAP, value).apply()
    }

    fun bootstrap(): String? = preferences.getString(KEY_BOOTSTRAP, null)

    fun completedOnboardingVersion(userId: Long): Int = preferences.getInt(onboardingCompletionKey(userId), 0)

    fun completeOnboarding(userId: Long, version: Int) {
        preferences.edit().putInt(onboardingCompletionKey(userId), version).apply()
    }

    fun clearTokens() {
        preferences.edit().remove(KEY_ACCESS_TOKEN).remove(KEY_REFRESH_TOKEN).remove(KEY_BOOTSTRAP).apply()
    }

    fun databasePassphrase(): ByteArray {
        var encoded = preferences.getString(KEY_DATABASE_KEY, null)
        if (encoded.isNullOrBlank()) {
            val bytes = ByteArray(32).also(SecureRandom()::nextBytes)
            encoded = Base64.encodeToString(bytes, Base64.NO_WRAP)
            preferences.edit().putString(KEY_DATABASE_KEY, encoded).apply()
        }
        return Base64.decode(encoded, Base64.NO_WRAP)
    }

    fun markDatabaseKeyRotation() {
        preferences.edit().putBoolean(KEY_ROTATE_DATABASE, true).apply()
    }

    @SuppressLint("ApplySharedPref")
    fun consumeDatabaseKeyRotation(): Boolean {
        val rotate = preferences.getBoolean(KEY_ROTATE_DATABASE, false)
        // The key must be durably removed before the encrypted database is reopened.
        if (rotate) preferences.edit().remove(KEY_ROTATE_DATABASE).remove(KEY_DATABASE_KEY).commit()
        return rotate
    }

    private companion object {
        const val KEY_ACCESS_TOKEN = "access_token"
        const val KEY_REFRESH_TOKEN = "refresh_token"
        const val KEY_DEVICE_ID = "device_id"
        const val KEY_DATABASE_KEY = "database_key"
        const val KEY_ROTATE_DATABASE = "rotate_database_key"
        const val KEY_BOOTSTRAP = "bootstrap_json"
    }
}
