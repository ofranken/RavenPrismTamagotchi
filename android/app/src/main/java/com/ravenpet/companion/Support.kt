package com.ravenpet.companion

import android.Manifest
import android.app.AppOpsManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Process
import org.json.JSONObject

/** Live values shared between the service and the screen (same process). */
object LinkState {
    @Volatile var running = false
    @Volatile var usageAccess = false
    @Volatile var screenOn = true
    @Volatile var foregroundPackage = ""
    @Volatile var foregroundLabel = ""
    @Volatile var stepsTotal: Long? = null
    @Volatile var discoveredHost = ""
    @Volatile var lastStatus: JSONObject? = null
    @Volatile var lastOkAt = 0L
    @Volatile var lastError = ""
}

object Prefs {
    const val DEFAULT_PORT = 8765
    private fun p(c: Context) = c.getSharedPreferences("raven", Context.MODE_PRIVATE)

    fun host(c: Context): String = p(c).getString("host", "") ?: ""
    fun setHost(c: Context, v: String) = p(c).edit().putString("host", v.trim()).apply()
    fun port(c: Context): Int = p(c).getInt("port", DEFAULT_PORT)
    fun setPort(c: Context, v: Int) = p(c).edit().putInt("port", v).apply()
    fun pairCode(c: Context): String = p(c).getString("pair", "") ?: ""
    fun setPairCode(c: Context, v: String) = p(c).edit().putString("pair", v.trim()).apply()
    fun autoDiscover(c: Context): Boolean = p(c).getBoolean("auto", true)
    fun setAutoDiscover(c: Context, v: Boolean) = p(c).edit().putBoolean("auto", v).apply()
    fun enabled(c: Context): Boolean = p(c).getBoolean("enabled", false)
    fun setEnabled(c: Context, v: Boolean) = p(c).edit().putBoolean("enabled", v).apply()
}

object Permissions {
    fun hasUsageAccess(c: Context): Boolean {
        val ops = c.getSystemService(AppOpsManager::class.java)
        val mode = ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), c.packageName)
        return mode == AppOpsManager.MODE_ALLOWED
    }

    fun hasActivityRecognition(c: Context): Boolean =
        c.checkSelfPermission(Manifest.permission.ACTIVITY_RECOGNITION) == PackageManager.PERMISSION_GRANTED
}

/** Restart the link after a reboot if the user had it switched on. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED && Prefs.enabled(context)) {
            RavenLinkService.start(context)
        }
    }
}
