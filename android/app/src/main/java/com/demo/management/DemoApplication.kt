package com.demo.management

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import com.demo.management.core.notification.NotificationSyncWorker
import com.demo.management.core.telemetry.TelemetryReporter
import com.demo.management.core.telemetry.TelemetrySyncWorker
import com.demo.management.core.sync.MobileSyncWorker
import com.demo.management.core.update.ApkUpdateManager
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

@HiltAndroidApp
class DemoApplication : Application(), Configuration.Provider {
    @Inject lateinit var workerFactory: HiltWorkerFactory
    @Inject lateinit var telemetryReporter: TelemetryReporter

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setWorkerFactory(workerFactory).build()

    override fun onCreate() {
        super.onCreate()
        NotificationSyncWorker.createChannels(this)
        NotificationSyncWorker.schedule(this)
        TelemetrySyncWorker.schedule(this)
        MobileSyncWorker.schedule(this)
        ApkUpdateManager.createChannel(this)
        val previousHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            telemetryReporter.recordCrash(error)
            previousHandler?.uncaughtException(thread, error)
        }
    }
}
