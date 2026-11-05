package com.demo.management.core.appearance

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.demo.designsystem.theme.AppearanceSettings
import com.demo.designsystem.theme.GlassPreference
import com.demo.designsystem.theme.LiquidThemeMode
import com.demo.designsystem.theme.MotionPreference
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.appearanceDataStore by preferencesDataStore(name = "liquid_appearance")

@Singleton
class AppearancePreferenceStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    val settings: Flow<AppearanceSettings> = context.appearanceDataStore.data.map { values ->
        AppearanceSettings(
            themeMode = LiquidThemeMode.fromWireName(values[THEME_MODE]),
            glassPreference = GlassPreference.fromWireName(values[GLASS_MODE]),
            motionPreference = MotionPreference.fromWireName(values[MOTION_MODE]),
        )
    }

    suspend fun setThemeMode(value: LiquidThemeMode) {
        context.appearanceDataStore.edit { it[THEME_MODE] = value.wireName }
    }

    suspend fun setGlassPreference(value: GlassPreference) {
        context.appearanceDataStore.edit { it[GLASS_MODE] = value.wireName }
    }

    suspend fun setMotionPreference(value: MotionPreference) {
        context.appearanceDataStore.edit { it[MOTION_MODE] = value.wireName }
    }

    private companion object {
        val THEME_MODE = stringPreferencesKey("theme_mode")
        val GLASS_MODE = stringPreferencesKey("glass_mode")
        val MOTION_MODE = stringPreferencesKey("motion_mode")
    }
}
