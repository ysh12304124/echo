package com.echo.phone.data.api

import android.content.Context
import com.echo.phone.BuildConfig
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object ApiClient {
    private const val PREFS_NAME = "echo_settings"
    private const val KEY_BACKEND = "selected_backend"
    private val DEFAULT_URL = BuildConfig.API_BASE_URL

    private val backendMap = mapOf(
        "153" to "http://192.168.0.153:8001/api/v1/",
        "200" to "http://192.168.0.200:8081/api/v1/",
    )

    fun getBaseUrl(context: Context): String {
        val key = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_BACKEND, "153") ?: "153"
        return backendMap[key] ?: DEFAULT_URL
    }

    private val logging = HttpLoggingInterceptor().apply {
        level = HttpLoggingInterceptor.Level.BODY
    }

    private val okHttp = OkHttpClient.Builder()
        .addInterceptor(logging)
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    lateinit var service: EchoApiService
        private set

    fun init(context: Context) {
        val baseUrl = getBaseUrl(context)
        service = Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(okHttp)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(EchoApiService::class.java)
    }
}