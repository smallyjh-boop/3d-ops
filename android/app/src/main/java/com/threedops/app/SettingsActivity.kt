package com.threedops.app

import android.app.Activity
import android.os.Bundle
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.RadioGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/** 服务器地址 + 打开哪个版本。第一次打开 App 时出现；以后在网页顶部 ⚙、连不上服务器的页面、退出对话框里能打开。 */
class SettingsActivity : AppCompatActivity() {
    private lateinit var url: EditText
    private lateinit var mode: RadioGroup
    private lateinit var status: TextView
    private lateinit var connect: Button
    private var failedFor: String? = null      // 测试连不上时，再点一次「还是保存」

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)
        url = findViewById(R.id.serverUrl)
        mode = findViewById(R.id.mode)
        status = findViewById(R.id.status)
        connect = findViewById(R.id.btnConnect)
        findViewById<TextView>(R.id.appVersion).text = getString(R.string.version_fmt, BuildConfig.VERSION_NAME)

        url.setText(Prefs.server(this).ifEmpty { Prefs.DEFAULT_SERVER })
        mode.check(
            when (Prefs.mode(this)) {
                "full" -> R.id.modeFull
                "phone" -> R.id.modePhone
                else -> R.id.modeAuto
            }
        )
        url.setOnEditorActionListener { _, id, _ ->
            if (id == EditorInfo.IME_ACTION_DONE) {
                test(); true
            } else false
        }
        connect.setOnClickListener { test() }
        findViewById<Button>(R.id.btnCancel).setOnClickListener {
            setResult(Activity.RESULT_CANCELED)
            finish()
        }
    }

    private fun modeValue() = when (mode.checkedRadioButtonId) {
        R.id.modeFull -> "full"
        R.id.modePhone -> "phone"
        else -> "auto"
    }

    private fun test() {
        val server = Prefs.normalize(url.text.toString())
        if (server == null) {
            status.text = getString(R.string.bad_url)
            return
        }
        if (failedFor == server) {             // 已经测过连不上，用户坚持保存（例如现在不在店里）
            save(server)
            return
        }
        status.text = getString(R.string.testing)
        connect.isEnabled = false
        thread {
            val result = try {
                val c = URL("$server/api/version").openConnection() as HttpURLConnection
                c.connectTimeout = 5000
                c.readTimeout = 5000
                c.instanceFollowRedirects = false
                val code = c.responseCode
                val body = if (code == 200) c.inputStream.bufferedReader().use { it.readText() } else ""
                c.disconnect()
                if (code == 200) Result.success(JSONObject(body).optString("version", "?")) else Result.failure(Exception("HTTP $code"))
            } catch (e: Exception) {
                Result.failure(e)
            }
            runOnUiThread {
                connect.isEnabled = true
                result.onSuccess { v ->
                    status.text = getString(R.string.test_ok, v)
                    save(server)
                }.onFailure { e ->
                    status.text = getString(R.string.test_fail, e.message ?: e.javaClass.simpleName)
                    failedFor = server
                    connect.text = getString(R.string.save_anyway)
                }
            }
        }
    }

    private fun save(server: String) {
        Prefs.save(this, server, modeValue())
        setResult(Activity.RESULT_OK)
        finish()
    }
}
