package com.threedops.app

import org.json.JSONObject

/**
 * 摄像头小窗里 ML Kit 认出来的文字 → 「像码的文字」（货位 A1-02-03、订单号、快递单号、SKU……）。
 * 哪些算「像码」由服务器给（/api/mobile/code-patterns，网页登录后通过 Android3D.setTextPatterns(json) 交过来）；
 * 没给就不认文字（只扫条码，和以前一样）。
 * 只是挑出来：O/0、I/1 这类错和「是系统里的哪个码」由网页再问服务器（/api/recog/text，和拍照读文字用同一个容错匹配）。
 * 防误读：同一段文字要在 confirmFrames 帧里都读到（默认 2 帧，1.5 秒内）才算。
 */
class TextCodes {
    data class Pattern(val type: String, val re: Regex)

    @Volatile
    var patterns: List<Pattern> = emptyList()
        private set
    private var minLen = 4
    private var maxLen = 40
    private var confirmFrames = 2
    private val pending = HashMap<String, Pair<Int, Long>>()     // 文字 → (看到几帧, 第一次看到的时间)

    val enabled: Boolean get() = patterns.isNotEmpty()

    /** 网页交过来的 JSON：{"patterns":[{"type":"location","re":"^…$"}], "min_len":4, "max_len":40, "confirm_frames":2} */
    fun update(json: String?) {
        try {
            val o = JSONObject(json ?: "{}")
            val arr = o.optJSONArray("patterns")
            val list = ArrayList<Pattern>()
            if (arr != null) {
                for (i in 0 until arr.length()) {
                    val p = arr.optJSONObject(i) ?: continue
                    try {
                        list.add(Pattern(p.optString("type", "code"), Regex(p.getString("re"))))
                    } catch (_: Exception) {
                        // 这条正则 Java 不认：跳过
                    }
                }
            }
            minLen = o.optInt("min_len", 4)
            maxLen = o.optInt("max_len", 40)
            confirmFrames = o.optInt("confirm_frames", 2).coerceIn(1, 5)
            patterns = list
        } catch (_: Exception) {
            patterns = emptyList()
        }
        synchronized(pending) { pending.clear() }
    }

    /** 一行 / 一个词 → 要试的写法（原样、去掉空格），都转大写。 */
    private fun variants(s: String): List<String> {
        val t = s.trim().uppercase().replace(Regex("\\s+"), " ")
        if (t.length < minLen || t.length > maxLen + 10) return emptyList()
        val noSpace = t.replace(" ", "")
        return if (noSpace != t) listOf(t, noSpace) else listOf(t)
    }

    fun looksLikeCode(s: String): Boolean {
        val ps = patterns
        if (ps.isEmpty()) return false
        for (v in variants(s)) {
            if (v.length < minLen || v.length > maxLen) continue
            if (ps.any { it.re.matches(v) }) return true
        }
        return false
    }

    /**
     * 这一帧认出来的文字（每行，以及每行里的词、相邻 2~3 个词拼起来）→ 像码的文字。
     * lines：每行的词列表（ML Kit 的 TextLine.elements）。
     */
    fun candidates(lines: List<List<String>>): List<String> {
        val out = LinkedHashSet<String>()
        for (words in lines) {
            val ws = words.filter { it.isNotBlank() }
            if (ws.isEmpty()) continue
            val tries = ArrayList<String>()
            tries.add(ws.joinToString(" "))
            for (i in ws.indices) {
                for (n in 1..3) {
                    if (i + n <= ws.size) tries.add(ws.subList(i, i + n).joinToString(" "))
                }
            }
            for (t in tries) {
                if (looksLikeCode(t)) {
                    out.add(t.trim().uppercase().replace(Regex("\\s+"), " "))
                }
            }
        }
        // 一行里同时有「A1-02-03」和「LOC A1-02-03」：只要最短的那个就够了（服务器容错时也会去掉多余的字）
        return out.filter { a -> out.none { b -> b != a && b.length < a.length && a.contains(b) } }
    }

    /** 连续几帧都读到才算（防止一闪而过的误读）。返回这一帧「确认了」的文字。 */
    fun confirm(found: List<String>, now: Long): List<String> {
        val ok = ArrayList<String>()
        synchronized(pending) {
            val it = pending.entries.iterator()
            while (it.hasNext()) if (now - it.next().value.second > 1500) it.remove()
            for (f in found) {
                val (n, first) = pending[f] ?: Pair(0, now)
                val n2 = n + 1
                if (n2 >= confirmFrames) {
                    ok.add(f)
                    pending.remove(f)
                } else {
                    pending[f] = Pair(n2, first)
                }
            }
        }
        return ok
    }
}
