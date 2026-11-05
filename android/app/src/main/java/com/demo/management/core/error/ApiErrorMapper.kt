package com.demo.management.core.error

object ApiErrorMapper {
    fun fromStatus(status: Int): String = when (status) {
        400 -> "请求内容有误，请检查后重试"
        401 -> "登录已过期，请重新登录"
        403 -> "当前账号没有此操作权限"
        404 -> "请求的数据不存在或已失效"
        409 -> "数据状态已变化，请刷新后重试"
        422 -> "提交内容有误，请检查必填项"
        in 500..599 -> "服务暂时不可用，请稍后重试"
        else -> "操作失败，请稍后重试"
    }

    fun fromPayload(payload: String?, status: Int): String {
        if (payload.isNullOrBlank()) return fromStatus(status)
        val message = Regex("\\\"message\\\"\\s*:\\s*\\\"((?:\\\\.|[^\\\"])*)\\\"").find(payload)?.groupValues?.getOrNull(1)?.unescapeJson()
        val requestId = Regex("\\\"request_id\\\"\\s*:\\s*\\\"((?:\\\\.|[^\\\"])*)\\\"").find(payload)?.groupValues?.getOrNull(1)?.unescapeJson()
        return if (!message.isNullOrBlank()) message + requestId?.takeIf { it.isNotBlank() }?.let { "（编号 $it）" }.orEmpty() else fromStatus(status)
    }

    fun fromThrowable(error: Throwable): String = when (error) {
        is retrofit2.HttpException -> fromPayload(error.response()?.errorBody()?.string(), error.code())
        is java.net.UnknownHostException -> "网络不可用，请检查网络连接"
        is java.net.SocketTimeoutException -> "网络连接超时，请稍后重试"
        is java.io.IOException -> "网络异常，请稍后重试"
        else -> error.message?.takeIf { it.isNotBlank() } ?: "操作失败，请稍后重试"
    }

    private fun String.unescapeJson(): String = replace("\\\"", "\"").replace("\\n", "\n").replace("\\\\", "\\")
}
