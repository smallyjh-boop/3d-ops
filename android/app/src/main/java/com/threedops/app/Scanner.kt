package com.threedops.app

import android.os.SystemClock
import android.util.Size
import androidx.annotation.OptIn
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * 像扫码枪一样的摄像头：一直开着连续识别（CameraX 预览 + ML Kit 条码识别），读到码就交给 onCode。
 * 去重：同一个码一直在镜头里只算一次——2 秒内又看到就不算（拿开 2 秒再对准才算第二次）。
 * 摄像头跟着 Activity 的生命周期：App 切到后台自动停，回来自动开。
 */
class Scanner(
    private val activity: AppCompatActivity,
    private val preview: PreviewView,
    private val onCode: (String) -> Unit,
) {
    companion object {
        const val DEDUP_MS = 2000L
    }

    private var provider: ProcessCameraProvider? = null
    private var camera: Camera? = null
    private var executor: ExecutorService? = null
    private val client = BarcodeScanning.getClient(
        BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_ALL_FORMATS).build()
    )
    private val seen = HashMap<String, Long>()
    private var torchOn = false
    var running = false
        private set

    fun start(onError: (Exception) -> Unit) {
        if (running) return
        running = true
        val future = ProcessCameraProvider.getInstance(activity)
        future.addListener({
            if (!running) return@addListener
            try {
                val p = future.get()
                provider = p
                val prev = Preview.Builder().build().also { it.setSurfaceProvider(preview.surfaceProvider) }
                val selector = ResolutionSelector.Builder()
                    .setResolutionStrategy(
                        ResolutionStrategy(Size(1280, 720), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER)
                    ).build()
                val ex = Executors.newSingleThreadExecutor()
                executor = ex
                val analysis = ImageAnalysis.Builder()
                    .setResolutionSelector(selector)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis.setAnalyzer(ex) { proxy -> analyze(proxy) }
                p.unbindAll()
                camera = p.bindToLifecycle(activity, CameraSelector.DEFAULT_BACK_CAMERA, prev, analysis)
                torchOn = false
            } catch (e: Exception) {
                running = false
                onError(e)
            }
        }, ContextCompat.getMainExecutor(activity))
    }

    fun stop() {
        running = false
        try {
            provider?.unbindAll()
        } catch (_: Exception) {
        }
        camera = null
        executor?.shutdown()
        executor = null
    }

    fun toggleTorch() {
        val c = camera ?: return
        if (!c.cameraInfo.hasFlashUnit()) return
        torchOn = !torchOn
        c.cameraControl.enableTorch(torchOn)
    }

    @OptIn(ExperimentalGetImage::class)
    private fun analyze(proxy: ImageProxy) {
        val img = proxy.image
        if (img == null || !running) {
            proxy.close()
            return
        }
        val input = InputImage.fromMediaImage(img, proxy.imageInfo.rotationDegrees)
        client.process(input)
            .addOnSuccessListener { list ->           // 在主线程上
                if (!running) return@addOnSuccessListener
                val now = SystemClock.elapsedRealtime()
                for (b in list) {
                    val v = b.rawValue?.trim() ?: continue
                    if (v.isEmpty()) continue
                    val last = seen[v] ?: 0L
                    seen[v] = now
                    if (now - last > DEDUP_MS) onCode(v)
                }
                if (seen.size > 100) {
                    val it = seen.entries.iterator()
                    while (it.hasNext()) if (now - it.next().value > 10_000) it.remove()
                }
            }
            .addOnCompleteListener { proxy.close() }
    }
}
