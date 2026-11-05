package com.demo.management.core.network

import com.demo.management.BuildConfig
import com.demo.management.core.auth.AuthInterceptor
import com.demo.management.core.auth.InMemoryTokenProvider
import com.demo.management.core.auth.RefreshAuthenticator
import com.demo.management.core.auth.TokenProvider
import com.demo.management.data.AuthApi
import com.demo.management.data.MobileApi
import com.demo.management.data.SyncApi
import com.demo.management.data.round3.CheckApi
import com.demo.management.data.round3.DataApi
import com.demo.management.data.round3.ToolsApi
import com.demo.management.data.round5.Round5Api
import com.demo.management.data.round6.Round6Api
import com.demo.management.core.telemetry.TelemetryInterceptor
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import javax.inject.Named
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {
    @Provides
    @Singleton
    fun provideTokenProvider(): TokenProvider = InMemoryTokenProvider()

    @Provides
    @Singleton
    fun provideMoshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    @Provides
    @Singleton
    @Named("bare")
    fun provideBareClient(): OkHttpClient = OkHttpClient.Builder().build()

    @Provides
    @Singleton
    fun provideAuthApi(moshi: Moshi, @Named("bare") client: OkHttpClient): AuthApi = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL)
        .client(client)
        .addConverterFactory(MoshiConverterFactory.create(moshi))
        .build()
        .create(AuthApi::class.java)

    @Provides
    @Singleton
    @Named("authenticated")
    fun provideAuthenticatedClient(
        authInterceptor: AuthInterceptor,
        authenticator: RefreshAuthenticator,
        telemetryInterceptor: TelemetryInterceptor,
    ): OkHttpClient {
        val logging = HttpLoggingInterceptor().apply {
            level = if (BuildConfig.DEBUG) HttpLoggingInterceptor.Level.BASIC else HttpLoggingInterceptor.Level.NONE
        }
        return OkHttpClient.Builder()
            .addInterceptor(authInterceptor)
            .authenticator(authenticator)
            .addInterceptor(telemetryInterceptor)
            .addInterceptor(logging)
            .build()
    }

    @Provides
    @Singleton
    fun provideMobileApi(moshi: Moshi, @Named("authenticated") client: OkHttpClient): MobileApi = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL)
        .client(client)
        .addConverterFactory(MoshiConverterFactory.create(moshi))
        .build()
        .create(MobileApi::class.java)

    @Provides
    @Singleton
    fun provideSyncApi(moshi: Moshi, @Named("authenticated") client: OkHttpClient): SyncApi =
        retrofit(moshi, client).create(SyncApi::class.java)

    private fun retrofit(moshi: Moshi, client: OkHttpClient): Retrofit = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL)
        .client(client)
        .addConverterFactory(MoshiConverterFactory.create(moshi))
        .build()

    @Provides
    @Singleton
    fun provideDataApi(moshi: Moshi, @Named("authenticated") client: OkHttpClient): DataApi =
        retrofit(moshi, client).create(DataApi::class.java)

    @Provides
    @Singleton
    fun provideCheckApi(moshi: Moshi, @Named("authenticated") client: OkHttpClient): CheckApi =
        retrofit(moshi, client).create(CheckApi::class.java)

    @Provides
    @Singleton
    fun provideToolsApi(moshi: Moshi, @Named("authenticated") client: OkHttpClient): ToolsApi =
        retrofit(moshi, client).create(ToolsApi::class.java)

    @Provides
    @Singleton
    fun provideRound5Api(moshi: Moshi, @Named("authenticated") client: OkHttpClient): Round5Api =
        retrofit(moshi, client).create(Round5Api::class.java)

    @Provides
    @Singleton
    fun provideRound6Api(moshi: Moshi, @Named("authenticated") client: OkHttpClient): Round6Api =
        retrofit(moshi, client).create(Round6Api::class.java)
}
