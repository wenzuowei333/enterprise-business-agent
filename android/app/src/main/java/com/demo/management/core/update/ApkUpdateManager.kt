package com.demo.management.core.update

import android.app.DownloadManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.Manifest
import android.content.pm.PackageManager
import android.os.Environment
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.FileProvider
import androidx.core.content.ContextCompat
import com.demo.management.R
import com.demo.management.data.MobileAppConfig
import java.io.File

object ApkUpdateManager {
    private const val PREFS = "mobile_update"
    private const val KEY_ID = "download_id"
    private const val KEY_SHA = "expected_sha"
    private const val FILE_NAME = "demo-management-update.apk"
    const val CHANNEL_ID = "mobile_update"

    fun start(context: Context, config: MobileAppConfig): Long {
        val url = config.downloadUrl?.takeIf { it.startsWith("https://") }
        if (url == null) {
            showResult(context, "更新地址未配置，请联系管理员", null)
            return -1L
        }
        val destination = File(context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), FILE_NAME)
        if (destination.exists()) destination.delete()
        val request = DownloadManager.Request(Uri.parse(url))
            .setTitle("星河演示管理中心 ${config.latestVersion}")
            .setDescription("正在下载应用更新")
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE)
            .setDestinationInExternalFilesDir(context, Environment.DIRECTORY_DOWNLOADS, FILE_NAME)
            .setAllowedOverMetered(true)
            .setAllowedOverRoaming(false)
        val id = context.getSystemService(DownloadManager::class.java).enqueue(request)
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putLong(KEY_ID, id)
            .putString(KEY_SHA, config.apkSha256.orEmpty().lowercase())
            .apply()
        return id
    }

    internal fun complete(context: Context, downloadId: Long) {
        val preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (preferences.getLong(KEY_ID, -1L) != downloadId) return
        val manager = context.getSystemService(DownloadManager::class.java)
        val cursor = manager.query(DownloadManager.Query().setFilterById(downloadId))
        cursor.use {
            if (!it.moveToFirst() || it.getInt(it.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS)) != DownloadManager.STATUS_SUCCESSFUL) {
                showResult(context, "更新下载失败", null)
                return
            }
        }
        val file = File(context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), FILE_NAME)
        val expected = preferences.getString(KEY_SHA, "").orEmpty()
        if (!file.exists() || file.inputStream().use { !ApkIntegrityPolicy.matches(it, expected) }) {
            file.delete()
            showResult(context, "更新包校验失败，请重新下载", null)
            return
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
        val installIntent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        showResult(context, "更新已下载，点击安装", installIntent)
    }

    fun createChannel(context: Context) {
        context.getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "应用更新", NotificationManager.IMPORTANCE_HIGH)
        )
    }

    private fun showResult(context: Context, message: String, intent: Intent?) {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            if (intent != null) runCatching { context.startActivity(intent) }
            return
        }
        val builder = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("星河演示管理中心")
            .setContentText(message)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
        if (intent != null) {
            builder.setContentIntent(
                PendingIntent.getActivity(context, 1200, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            )
        }
        runCatching { NotificationManagerCompat.from(context).notify(1200, builder.build()) }
    }

}

class ApkDownloadReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != DownloadManager.ACTION_DOWNLOAD_COMPLETE) return
        ApkUpdateManager.complete(context, intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L))
    }
}
