package com.ravenpet.companion

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class MainActivity : Activity() {

    private val ui = Handler(Looper.getMainLooper())
    private lateinit var status: TextView
    private lateinit var hostField: EditText
    private lateinit var autoBox: CheckBox
    private lateinit var usageButton: Button
    private lateinit var stepsButton: Button
    private lateinit var toggleButton: Button

    private val refresh = object : Runnable {
        override fun run() {
            render()
            ui.postDelayed(this, 1_000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 3, pad, pad)
        }

        col.addView(TextView(this).apply {
            text = "Raven Pet"
            textSize = 28f
            setTypeface(typeface, Typeface.BOLD)
        })
        col.addView(TextView(this).apply {
            text = "Instagram, TikTok, X and Facebook hurt your raven. Email, Outlook, Canvas and Zoom " +
                "feed and pet it. Walking plays with it, and putting your phone down lets it rest."
            setPadding(0, pad / 2, 0, pad)
        })

        status = TextView(this).apply {
            typeface = Typeface.MONOSPACE
            textSize = 14f
            setPadding(0, 0, 0, pad)
        }
        col.addView(status)

        usageButton = Button(this).apply {
            text = "Grant usage access"
            setOnClickListener { startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)) }
        }
        stepsButton = Button(this).apply {
            text = "Allow step tracking"
            setOnClickListener { requestRuntimePermissions() }
        }
        toggleButton = Button(this).apply {
            setOnClickListener {
                if (LinkState.running) {
                    Prefs.setEnabled(this@MainActivity, false)
                    RavenLinkService.stop(this@MainActivity)
                } else {
                    Prefs.setEnabled(this@MainActivity, true)
                    RavenLinkService.start(this@MainActivity)
                }
                ui.postDelayed({ render() }, 300)
            }
        }
        col.addView(usageButton)
        col.addView(stepsButton)
        col.addView(toggleButton)

        col.addView(TextView(this).apply {
            text = "Glasses address"
            setPadding(0, pad, 0, 0)
        })
        hostField = EditText(this).apply {
            hint = "auto (e.g. 192.168.1.42)"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setText(Prefs.host(this@MainActivity))
        }
        col.addView(hostField)
        autoBox = CheckBox(this).apply {
            text = "Find my Raven automatically"
            isChecked = Prefs.autoDiscover(this@MainActivity)
            setOnCheckedChangeListener { _, checked -> Prefs.setAutoDiscover(this@MainActivity, checked) }
        }
        col.addView(autoBox)
        col.addView(Button(this).apply {
            text = "Save address"
            setOnClickListener {
                val v = hostField.text.toString().trim()
                val (host, port) = if (":" in v) v.substringBefore(":") to (v.substringAfter(":").toIntOrNull() ?: Prefs.DEFAULT_PORT)
                    else v to Prefs.DEFAULT_PORT
                Prefs.setHost(this@MainActivity, host)
                Prefs.setPort(this@MainActivity, port)
                Prefs.setAutoDiscover(this@MainActivity, false)
                autoBox.isChecked = false
            }
        })

        setContentView(ScrollView(this).apply {
            setBackgroundColor(Color.rgb(16, 16, 28))
            addView(col)
        })
        requestRuntimePermissions()
    }

    override fun onResume() {
        super.onResume()
        if (Prefs.enabled(this) && !LinkState.running && Permissions.hasUsageAccess(this)) {
            RavenLinkService.start(this)
        }
        ui.post(refresh)
    }

    override fun onPause() {
        ui.removeCallbacks(refresh)
        super.onPause()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        // The step listener is registered when the service starts, so restart it to pick up the new permission.
        if (LinkState.running) {
            RavenLinkService.stop(this)
            ui.postDelayed({ RavenLinkService.start(this) }, 300)
        }
    }

    private fun requestRuntimePermissions() {
        val wanted = mutableListOf(Manifest.permission.ACTIVITY_RECOGNITION)
        if (android.os.Build.VERSION.SDK_INT >= 33) wanted += Manifest.permission.POST_NOTIFICATIONS
        val missing = wanted.filter { checkSelfPermission(it) != android.content.pm.PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1)
    }

    private fun render() {
        val hasUsage = Permissions.hasUsageAccess(this)
        usageButton.visibility = if (hasUsage) View.GONE else View.VISIBLE
        stepsButton.visibility = if (Permissions.hasActivityRecognition(this)) View.GONE else View.VISIBLE
        toggleButton.text = if (LinkState.running) "Stop sending to Raven" else "Start sending to Raven"
        if (!hostField.hasFocus() && Prefs.autoDiscover(this)) hostField.setText(Prefs.host(this))

        val s = LinkState.lastStatus
        val ago = if (LinkState.lastOkAt == 0L) "never" else "${(System.currentTimeMillis() - LinkState.lastOkAt) / 1000}s ago"
        val app = when {
            !LinkState.screenOn -> "(screen off - resting)"
            LinkState.foregroundLabel.isNotEmpty() -> "${LinkState.foregroundLabel}\n           ${LinkState.foregroundPackage}"
            else -> LinkState.foregroundPackage.ifEmpty { "?" }
        }
        val sb = StringBuilder()
        sb.append("Link:      ").append(if (LinkState.running) "running" else "stopped").append('\n')
        sb.append("Usage:     ").append(if (hasUsage) "granted" else "NOT GRANTED").append('\n')
        sb.append("Glasses:   ").append(Prefs.host(this).ifEmpty { "searching..." }).append(':').append(Prefs.port(this)).append('\n')
        sb.append("Contact:   ").append(ago).append('\n')
        sb.append("Now:       ").append(app).append('\n')
        sb.append("Raven sees: ").append(s?.optString("activity")?.uppercase() ?: "-").append('\n')
        sb.append("Steps:     ").append(LinkState.stepsTotal?.toString() ?: "-")
        s?.let { sb.append("  (today ").append(it.optInt("steps_today")).append(")") }
        sb.append('\n')
        sb.append("Brightness: ").append(LinkState.brightness?.let { "${(it * 100).toInt()}%" } ?: "-")
        sb.append("  Light: ").append(LinkState.lux?.let { "${it.toInt()} lux" } ?: "-").append('\n')
        if (s?.optBoolean("sunglasses") == true) sb.append("Sunny! Raven has its shades on 😎\n")
        if (s != null) {
            fun v(k: String) = s.optDouble(k, 0.0).toInt()
            sb.append("\nHealth ${v("health")}   Food ${v("food")}\nEnergy ${v("energy")}   Play ${v("play")}\n")
            sb.append("Mood: ").append(s.optString("mood")).append('\n')
        }
        if (LinkState.lastError.isNotEmpty()) sb.append("\n").append(LinkState.lastError)
        status.text = sb.toString()
    }
}
