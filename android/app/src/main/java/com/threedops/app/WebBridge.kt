package com.threedops.app

import android.webkit.JavascriptInterface

/**
 * 网页里的 window.Android3D（只给自己服务器的页面用）：
 *   isApp()  isTablet()  version()
 *   startScan() / stopScan()   打开 / 关上面的摄像头小窗；读到的码回调 window.onNativeScan(code)
 *   beep("ok" | "warn" | "error")   扫码结果的声音 + 震动
 *   openSettings()   App 设置（服务器地址、手机版 / 网页版）
 *   print()          打印当前页（网页的 window.print 换成这个）
 * 这些方法在后台线程被调用，要切回主线程做事。
 */
class WebBridge(private val a: MainActivity) {
    @JavascriptInterface
    fun isApp(): Boolean = true

    @JavascriptInterface
    fun isTablet(): Boolean = a.isTablet

    @JavascriptInterface
    fun version(): String = BuildConfig.VERSION_NAME

    @JavascriptInterface
    fun startScan() = a.runOnUiThread { a.startScan() }

    @JavascriptInterface
    fun stopScan() = a.runOnUiThread { a.stopScan() }

    @JavascriptInterface
    fun beep(kind: String?) {
        val k = when (kind) {
            "ok", "true" -> "ok"
            "warn" -> "warn"
            else -> "error"
        }
        a.runOnUiThread { a.feedback.play(k) }
    }

    @JavascriptInterface
    fun openSettings() = a.runOnUiThread { a.openSettings() }

    @JavascriptInterface
    fun print() = a.runOnUiThread { a.printPage() }
}
