package com.demo.management.core.sync

import retrofit2.HttpException
import java.io.IOException

object NetworkFailurePolicy {
    fun isRetryable(error: Throwable): Boolean = when (error) {
        is IOException -> true
        is HttpException -> error.code() == 408 || error.code() == 429 || error.code() >= 500
        else -> false
    }
}
