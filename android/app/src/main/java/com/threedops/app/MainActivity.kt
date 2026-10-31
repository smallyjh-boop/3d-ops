package com.threedops.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.print.PrintAttributes
import android.print.PrintManager
import android.provider.MediaStore
import android.view.View
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.PermissionRequest
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONObject
import java.io.File

/**
 * WebView 外壳：打开 NAS 上的 3D 运营系统。平板打开完整网页版「/」，手机打开扫码页「/m」（设置里可以换）。
 * 原生的东西：上面一条摄像头小窗连续扫码（Scanner）、扫码声音震动（Feedback）、拍照上传、下载面单 PDF、打印、返回键。
 */
class MainActivity : AppCompatActivity() {
    lateinit var feedback: Feedback
        private set
    val isTablet: Boolean get() = resources.getBoolean(R.bool.is_tablet)

    private lateinit var web: WebView
    private lateinit var strip: FrameLayout
    private lateinit var progress: ProgressBar
    private lateinit var errorPanel: LinearLayout
    private lateinit var lastCode: TextView
    private lateinit var scanner: Scanner

    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var photoUri: Uri? = null
    private var afterCameraPermission: (() -> Unit)? = null
    private var loadedServer = ""

    private val cameraPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        val next = afterCameraPermission
        afterCameraPermission = null
        if (granted) {
            next?.invoke()
        } else {
            Toast.makeText(this, R.string.cam_denied, Toast.LENGTH_LONG).show()
            js("window.SCAN && SCAN.stop && SCAN.stop()")
            if (next != null && fileCallback != null) openChooser(false)
        }
    }

    private val chooser = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        val cb = fileCallback ?: return@registerForActivityResult
        fileCallback = null
        var uris: Array<Uri>? = null
        if (res.resultCode == Activity.RESULT_OK) {
            val data = res.data
            val clip = data?.clipData
            uris = when {
                clip != null && clip.itemCount > 0 -> Array(clip.itemCount) { clip.getItemAt(it).uri }
                data?.data != null -> arrayOf(data.data!!)
                photoUri != null && photoTaken() -> arrayOf(photoUri!!)
                else -> null
            }
        }
        cb.onReceiveValue(uris)
    }

    private val settings = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        if (res.resultCode == Activity.RESULT_OK) loadHome()
        else if (Prefs.server(this).isEmpty()) finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        web = findViewById(R.id.web)
        strip = findViewById(R.id.scanStrip)
        progress = findViewById(R.id.progress)
        errorPanel = findViewById(R.id.errorPanel)
        lastCode = findViewById(R.id.lastCode)
        feedback = Feedback(this)
        scanner = Scanner(this, findViewById<PreviewView>(R.id.preview)) { code -> onCode(code) }

        // 摄像头小窗 = 屏幕高度的 1/4
        strip.layoutParams = strip.layoutParams.apply { height = maxOf(resources.displayMetrics.heightPixels / 4, dp(140)) }
        findViewById<View>(R.id.btnTorch).setOnClickListener { scanner.toggleTorch() }
        findViewById<View>(R.id.btnCloseCam).setOnClickListener { js("window.SCAN && SCAN.stop ? SCAN.stop() : 0"); stopScan() }
        findViewById<Button>(R.id.btnRetry).setOnClickListener { loadHome() }
        findViewById<Button>(R.id.btnSettings).setOnClickListener { openSettings() }

        setupWeb()
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (errorPanel.visibility != View.VISIBLE && web.canGoBack()) web.goBack() else askExit()
            }
        })

        if (Prefs.server(this).isEmpty()) {
            openSettings()
        } else if (savedInstanceState == null || web.restoreState(savedInstanceState) == null) {
            loadHome()
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
    }

    override fun onDestroy() {
        scanner.stop()
        feedback.release()
        web.destroy()
        super.onDestroy()
    }

    // ---------------- 网页 ----------------
    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWeb() {
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            @Suppress("DEPRECATION")
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = false
            loadWithOverviewMode = true
            useWideViewPort = true
            setSupportZoom(true)
            builtInZoomControls = true
            displayZoomControls = false
            setSupportMultipleWindows(false)          // target=_blank（打印页、面单）在同一个窗口打开，返回键回来
            javaScriptCanOpenWindowsAutomatically = true
            allowFileAccess = false
            cacheMode = WebSettings.LOAD_DEFAULT
            textZoom = 100
            userAgentString = "$userAgentString 3DOpsApp/${BuildConfig.VERSION_NAME}"
        }
        CookieManager.getInstance().setAcceptCookie(true)
        web.addJavascriptInterface(WebBridge(this), "Android3D")
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            WebViewCompat.addDocumentStartJavaScript(web, PRINT_JS, setOf("*"))
        }

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val u = request.url
                if (u.scheme == "http" || u.scheme == "https") {
                    if (sameServer(u)) return false
                }
                openExternal(u)                      // 别的网站（GitHub、Tailscale 后台……）用手机浏览器打开
                return true
            }

            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                progress.visibility = View.VISIBLE
                if (scanner.running) stopScan()      // 换页面先关摄像头；新页面要扫码会自己再开
            }

            override fun onPageFinished(view: WebView, url: String?) {
                progress.visibility = View.GONE
                view.evaluateJavascript(PRINT_JS, null)
                CookieManager.getInstance().flush()
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) showError(request.url.toString())
            }
        }

        web.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) {
                progress.progress = newProgress
            }

            override fun onShowFileChooser(view: WebView, cb: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = cb
                val accept = params.acceptTypes.joinToString(",").lowercase()
                val image = accept.isBlank() || accept.contains("image")
                multiple = params.mode == FileChooserParams.MODE_OPEN_MULTIPLE
                mime = if (image && !accept.contains(".")) "image/*" else "*/*"
                if (image) {
                    val go = { openChooser(true, params.isCaptureEnabled) }
                    if (hasCamera()) go() else {
                        afterCameraPermission = go
                        cameraPermission.launch(Manifest.permission.CAMERA)
                    }
                } else openChooser(false)
                return true
            }

            override fun onPermissionRequest(request: PermissionRequest) {
                val want = request.resources.filter { it == PermissionRequest.RESOURCE_VIDEO_CAPTURE }
                if (want.isNotEmpty() && hasCamera()) request.grant(want.toTypedArray()) else request.deny()
            }
        }

        web.setDownloadListener { url, ua, cd, mimeType, _ -> download(url, ua, cd, mimeType) }
    }

    private var multiple = false
    private var mime = "*/*"

    private fun openChooser(withCamera: Boolean, captureOnly: Boolean = false) {
        val content = Intent(Intent.ACTION_GET_CONTENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = mime
            if (multiple) putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        }
        var camera: Intent? = null
        photoUri = null
        if (withCamera && hasCamera()) {
            val dir = File(cacheDir, "photos").apply { mkdirs() }
            dir.listFiles()?.filter { System.currentTimeMillis() - it.lastModified() > 86_400_000 }?.forEach { it.delete() }
            val f = File(dir, "p_${System.currentTimeMillis()}.jpg")
            val uri = FileProvider.getUriForFile(this, "$packageName.files", f)
            photoUri = uri
            camera = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                putExtra(MediaStore.EXTRA_OUTPUT, uri)
                addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
        }
        val intent = if (camera != null && captureOnly) camera else Intent.createChooser(content, getString(R.string.choose_photo)).apply {
            if (camera != null) putExtra(Intent.EXTRA_INITIAL_INTENTS, arrayOf(camera))
        }
        try {
            chooser.launch(intent)
        } catch (e: ActivityNotFoundException) {
            fileCallback?.onReceiveValue(null)
            fileCallback = null
        }
    }

    private fun photoTaken(): Boolean = try {
        contentResolver.openInputStream(photoUri!!)?.use { it.available() > 0 } ?: false
    } catch (e: Exception) {
        false
    }

    private fun download(url: String, ua: String, cd: String?, mimeType: String?) {
        try {
            val name = URLUtil.guessFileName(url, cd, mimeType)
            val req = DownloadManager.Request(Uri.parse(url)).apply {
                CookieManager.getInstance().getCookie(url)?.let { addRequestHeader("Cookie", it) }
                addRequestHeader("User-Agent", ua)
                if (!mimeType.isNullOrBlank()) setMimeType(mimeType)
                setTitle(name)
                setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                if (Build.VERSION.SDK_INT >= 29) setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
                else setDestinationInExternalFilesDir(this@MainActivity, Environment.DIRECTORY_DOWNLOADS, name)
            }
            (getSystemService(DOWNLOAD_SERVICE) as DownloadManager).enqueue(req)
            Toast.makeText(this, getString(R.string.download_started, name), Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            openExternal(Uri.parse(url))
        }
    }

    fun printPage() {
        val pm = getSystemService(PRINT_SERVICE) as? PrintManager
        if (pm == null) {
            Toast.makeText(this, R.string.no_print, Toast.LENGTH_SHORT).show()
            return
        }
        val title = (web.title ?: getString(R.string.app_name)).ifBlank { getString(R.string.app_name) }
        pm.print(title, web.createPrintDocumentAdapter(title), PrintAttributes.Builder().build())
    }

    private fun sameServer(u: Uri): Boolean {
        val s = Uri.parse(loadedServer.ifEmpty { Prefs.server(this) })
        return u.host.equals(s.host, true) && portOf(u) == portOf(s)
    }

    private fun portOf(u: Uri) = if (u.port > 0) u.port else if (u.scheme == "https") 443 else 80

    private fun openExternal(u: Uri) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, u))
        } catch (_: ActivityNotFoundException) {
        }
    }

    fun loadHome() {
        val server = Prefs.server(this)
        if (server.isEmpty()) {
            openSettings(); return
        }
        val phone = when (Prefs.mode(this)) {
            "full" -> false
            "phone" -> true
            else -> !isTablet
        }
        errorPanel.visibility = View.GONE
        web.visibility = View.VISIBLE
        if (server != loadedServer) web.clearHistory()
        loadedServer = server
        web.loadUrl(server + if (phone) "/m" else "/")
    }

    private fun showError(url: String) {
        stopScan()
        findViewById<TextView>(R.id.errorUrl).text = url
        errorPanel.visibility = View.VISIBLE
    }

    fun openSettings() {
        settings.launch(Intent(this, SettingsActivity::class.java))
    }

    private fun askExit() {
        AlertDialog.Builder(this)
            .setMessage(R.string.exit_q)
            .setPositiveButton(R.string.exit) { _, _ -> finish() }
            .setNeutralButton(R.string.settings) { _, _ -> openSettings() }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    // ---------------- 扫码 ----------------
    private fun hasCamera() = ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    fun startScan() {
        if (!hasCamera()) {
            afterCameraPermission = { startScan() }
            cameraPermission.launch(Manifest.permission.CAMERA)
            return
        }
        strip.visibility = View.VISIBLE
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        scanner.start { _ ->
            Toast.makeText(this, R.string.cam_error, Toast.LENGTH_LONG).show()
            stopScan()
        }
    }

    fun stopScan() {
        scanner.stop()
        strip.visibility = View.GONE
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private fun onCode(code: String) {
        lastCode.text = code
        js("window.onNativeScan && window.onNativeScan(${JSONObject.quote(code)})")
    }

    private fun js(s: String) = web.evaluateJavascript(s, null)

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    companion object {
        /** 网页的 window.print() 在 WebView 里没反应：换成安卓的打印（可以选打印机、存 PDF）。 */
        private const val PRINT_JS =
            "(function(){if(window.Android3D&&!window.__p3d){window.__p3d=1;window.print=function(){Android3D.print()};}})();"
    }
}
