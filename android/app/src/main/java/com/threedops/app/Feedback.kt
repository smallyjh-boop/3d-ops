package com.threedops.app

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

/** 扫码反馈：成功「嘀」+ 短震；警告两声 + 两下短震；出错长鸣 + 两下长震（网页里根据结果调 Android3D.beep）。 */
class Feedback(context: Context) {
    private val tone: ToneGenerator? = try {
        ToneGenerator(AudioManager.STREAM_MUSIC, 95)
    } catch (e: RuntimeException) {
        null
    }

    private val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= 31) {
        (context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager)?.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
    }

    fun play(kind: String) {
        when (kind) {
            "ok" -> {
                tone?.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
                vibrate(longArrayOf(0, 60))
            }
            "warn" -> {
                tone?.startTone(ToneGenerator.TONE_PROP_BEEP2, 320)
                vibrate(longArrayOf(0, 80, 90, 80))
            }
            else -> {
                tone?.startTone(ToneGenerator.TONE_SUP_ERROR, 900)
                vibrate(longArrayOf(0, 500, 120, 500))
            }
        }
    }

    private fun vibrate(pattern: LongArray) {
        val v = vibrator ?: return
        if (!v.hasVibrator()) return
        if (Build.VERSION.SDK_INT >= 26) {
            v.vibrate(VibrationEffect.createWaveform(pattern, -1))
        } else {
            @Suppress("DEPRECATION")
            v.vibrate(pattern, -1)
        }
    }

    fun release() {
        tone?.release()
    }
}
