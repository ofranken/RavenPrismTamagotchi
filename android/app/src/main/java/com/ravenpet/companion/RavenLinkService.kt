package com.ravenpet.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.net.wifi.WifiManager
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.URL

/**
 * Foreground service that tells the Raven Prism glasses what the phone is doing:
 *  - which app is in the foreground (UsageStatsManager)
 *  - whether the screen is on (rest / sleep tracking)
 *  - the cumulative hardware step counter (play)
 *
 * Heartbeats go out every [HEARTBEAT_MS] and immediately whenever something changes.
 */
class RavenLinkService : Service(), SensorEventListener {

    companion object {
        const val TAG = "RavenLink"
        const val CHANNEL_ID = "raven_link"
        const val NOTIFICATION_ID = 1
        const val POLL_MS = 1_000L
        const val HEARTBEAT_MS = 5_000L
        const val BEACON_PORT = 47800

        fun start(context: Context) {
            context.startForegroundService(Intent(context, RavenLinkService::class.java))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, RavenLinkService::class.java))
        }
    }

    private lateinit var worker: HandlerThread
    private lateinit var handler: Handler
    private lateinit var usage: UsageStatsManager
    private lateinit var power: PowerManager
    private var sensors: SensorManager? = null
    private var multicastLock: WifiManager.MulticastLock? = null
    @Volatile private var discoverySocket: DatagramSocket? = null

    private var lastEventQuery = 0L
    private var lastSentAt = 0L
    private var lastSentKey = ""

    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            // Screen changes are sent right away so the raven knows you put the phone down / picked it up.
            handler.post { poll(force = true) }
        }
    }

    private val pollTask = object : Runnable {
        override fun run() {
            poll(force = false)
            handler.postDelayed(this, POLL_MS)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        usage = getSystemService(UsageStatsManager::class.java)
        power = getSystemService(PowerManager::class.java)
        createChannel()
        startForeground(
            NOTIFICATION_ID,
            buildNotification("Connecting to your Raven..."),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
        )
        LinkState.running = true

        worker = HandlerThread("raven-link").apply { start() }
        handler = Handler(worker.looper)

        registerReceiver(screenReceiver, IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_USER_PRESENT)
        })

        if (Permissions.hasActivityRecognition(this)) {
            sensors = getSystemService(SensorManager::class.java)
            val stepCounter = sensors?.getDefaultSensor(Sensor.TYPE_STEP_COUNTER)
            if (stepCounter != null) {
                sensors?.registerListener(this, stepCounter, SensorManager.SENSOR_DELAY_NORMAL, 10_000_000)
            } else {
                Log.w(TAG, "no step counter on this device")
            }
        }

        lastEventQuery = System.currentTimeMillis() - 60 * 60 * 1000L
        LinkState.foregroundPackage = currentForegroundFallback()
        startDiscovery()
        handler.post(pollTask)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onDestroy() {
        LinkState.running = false
        unregisterReceiver(screenReceiver)
        sensors?.unregisterListener(this)
        discoverySocket?.close()
        multicastLock?.let { if (it.isHeld) it.release() }
        handler.removeCallbacksAndMessages(null)
        worker.quitSafely()
        super.onDestroy()
    }

    // ------------------------------------------------------------------ steps
    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type == Sensor.TYPE_STEP_COUNTER) {
            LinkState.stepsTotal = event.values[0].toLong()
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    // ------------------------------------------------------------------ foreground app
    /** Walks new usage events and remembers the most recently resumed app. */
    private fun updateForegroundApp() {
        val now = System.currentTimeMillis()
        val events = usage.queryEvents(lastEventQuery, now)
        val e = UsageEvents.Event()
        var latest: String? = null
        var latestTime = 0L
        while (events.hasNextEvent()) {
            events.getNextEvent(e)
            if (e.eventType == UsageEvents.Event.ACTIVITY_RESUMED && e.timeStamp >= latestTime) {
                latest = e.packageName
                latestTime = e.timeStamp
            }
        }
        lastEventQuery = now - 2_000 // small overlap so no event slips between queries
        if (latest != null) LinkState.foregroundPackage = latest
    }

    /** On start-up, ask for the last app used in the past hour. */
    private fun currentForegroundFallback(): String {
        val now = System.currentTimeMillis()
        val stats = usage.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, now - 3_600_000L, now)
        return stats?.maxByOrNull { it.lastTimeUsed }?.packageName ?: ""
    }

    private fun labelFor(pkg: String): String = try {
        packageManager.getApplicationLabel(packageManager.getApplicationInfo(pkg, 0)).toString()
    } catch (e: Exception) {
        pkg
    }

    // ------------------------------------------------------------------ heartbeat
    private fun poll(force: Boolean) {
        if (Permissions.hasUsageAccess(this)) {
            updateForegroundApp()
            LinkState.usageAccess = true
        } else {
            LinkState.usageAccess = false
        }
        val screenOn = power.isInteractive
        LinkState.screenOn = screenOn
        val pkg = if (screenOn) LinkState.foregroundPackage else ""
        val key = "$pkg|$screenOn"
        val now = System.currentTimeMillis()
        if (!force && key == lastSentKey && now - lastSentAt < HEARTBEAT_MS) return
        lastSentKey = key
        lastSentAt = now
        send(pkg, screenOn)
    }

    private fun send(pkg: String, screenOn: Boolean) {
        val host = Prefs.host(this)
        if (host.isBlank()) {
            LinkState.lastError = "Looking for your Raven... (or enter its IP)"
            updateNotification("Looking for your Raven...")
            return
        }
        val label = if (pkg.isEmpty()) "" else labelFor(pkg)
        LinkState.foregroundLabel = label
        val body = JSONObject().apply {
            put("package", pkg)
            put("label", label)
            put("screen_on", screenOn)
            LinkState.stepsTotal?.let { put("steps_total", it) }
        }.toString()
        try {
            val conn = URL("http://$host:${Prefs.port(this)}/activity").openConnection() as HttpURLConnection
            conn.connectTimeout = 2_000
            conn.readTimeout = 2_000
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            val pair = Prefs.pairCode(this)
            if (pair.isNotBlank()) conn.setRequestProperty("X-Raven-Pair", pair)
            conn.outputStream.use { it.write(body.toByteArray()) }
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""
            conn.disconnect()
            if (code !in 200..299) throw IllegalStateException("HTTP $code $text")
            Log.i(TAG, "sent ${pkg.ifEmpty { "-" }} screen_on=$screenOn -> glasses sees ${JSONObject(text.ifBlank { "{}" }).optString("activity")}")
            val status = JSONObject(text.ifBlank { "{}" })
            LinkState.lastStatus = status
            LinkState.lastOkAt = System.currentTimeMillis()
            LinkState.lastError = ""
            updateNotification(statusLine(status))
        } catch (e: Exception) {
            Log.w(TAG, "send to $host failed: ${e.message}")
            LinkState.lastError = "Can't reach Raven at $host: ${e.message}"
            updateNotification("Can't reach your Raven ($host)")
        }
    }

    private fun statusLine(s: JSONObject): String {
        if (s.optBoolean("alive", true).not()) return "Your raven fainted - be productive to revive it"
        fun v(k: String) = s.optDouble(k, 0.0).toInt()
        return "❤ ${v("health")}  🍒 ${v("food")}  ⚡ ${v("energy")}  👣 ${v("play")}  · ${s.optString("mood")}"
    }

    // ------------------------------------------------------------------ discovery
    /** The glasses broadcast {"service":"raven-pet","port":8765} on UDP 47800. */
    private fun startDiscovery() {
        val wifi = applicationContext.getSystemService(WifiManager::class.java)
        multicastLock = wifi?.createMulticastLock("raven-pet")?.apply {
            setReferenceCounted(false)
            acquire()
        }
        Thread({
            try {
                val sock = DatagramSocket(null).apply {
                    reuseAddress = true
                    broadcast = true
                    bind(InetSocketAddress(BEACON_PORT))
                }
                discoverySocket = sock
                val buf = ByteArray(512)
                while (!sock.isClosed) {
                    val packet = DatagramPacket(buf, buf.size)
                    sock.receive(packet)
                    val json = JSONObject(String(packet.data, 0, packet.length))
                    if (json.optString("service") != "raven-pet") continue
                    val ip = packet.address.hostAddress ?: continue
                    LinkState.discoveredHost = ip
                    if (Prefs.autoDiscover(this)) {
                        Prefs.setHost(this, ip)
                        Prefs.setPort(this, json.optInt("port", Prefs.DEFAULT_PORT))
                    }
                }
            } catch (e: Exception) {
                Log.i(TAG, "discovery stopped: ${e.message}")
            }
        }, "raven-discovery").apply { isDaemon = true }.start()
    }

    // ------------------------------------------------------------------ notification
    private fun createChannel() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "Raven link", NotificationManager.IMPORTANCE_LOW)
        )
    }

    private fun buildNotification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_raven)
            .setContentTitle("Raven Pet")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    private var lastNotificationText = ""
    private fun updateNotification(text: String) {
        if (text == lastNotificationText) return
        lastNotificationText = text
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, buildNotification(text))
    }
}
