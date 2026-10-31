package com.threedops.app

import android.content.Context

/** App 记住的东西：服务器地址、打开哪个版本（auto 自动 / full 完整网页版 / phone 手机扫码版）。 */
object Prefs {
    const val DEFAULT_SERVER = "http://192.168.31.200:8790"
    private const val FILE = "app"

    private fun sp(c: Context) = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun server(c: Context): String = sp(c).getString("server", "") ?: ""
    fun mode(c: Context): String = sp(c).getString("mode", "auto") ?: "auto"

    fun save(c: Context, server: String, mode: String) {
        sp(c).edit().putString("server", server).putString("mode", mode).apply()
    }

    /** 「192.168.31.200:8790/」→「http://192.168.31.200:8790」；不像地址返回 null。 */
    fun normalize(raw: String): String? {
        var s = raw.trim().trimEnd('/')
        if (s.isEmpty()) return null
        if (!s.startsWith("http://", true) && !s.startsWith("https://", true)) s = "http://$s"
        val u = android.net.Uri.parse(s)
        if (u.host.isNullOrBlank()) return null
        val port = if (u.port > 0) ":${u.port}" else ""
        return "${u.scheme!!.lowercase()}://${u.host}$port"
    }
}
