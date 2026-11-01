package com.threedops.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 摄像头文字识别挑「像码的文字」：用服务器真实给出的正则（test/resources/code_patterns.json，由 /api/mobile/code-patterns 生成），
 * 喂 ML Kit 常见的读法（O/0、I/1、S/5、B/8 认错，少横杠，多空格，一行里还有别的字）。
 * 是系统里的哪个码由服务器的容错匹配决定（modules/recog/textmatch.py，Python 测试里测），这里只测「挑出来、不挑垃圾」。
 */
class TextCodesTest {
    private fun codes(): TextCodes {
        val json = javaClass.classLoader!!.getResource("code_patterns.json")!!.readText()
        return TextCodes().also { it.update(json) }
    }

    private fun words(s: String) = listOf(s.split(" "))

    @Test
    fun patternsLoad() {
        val t = codes()
        assertTrue(t.enabled)
        assertTrue(t.patterns.size >= 6)
    }

    @Test
    fun picksCodesWithTypicalOcrMistakes() {
        val t = codes()
        for (s in listOf("A1-02-03", "A1-O2-O3", "Al-02-O3", "A1 02 03", "a1-02-03", "3DP0001-WH", "3DPOOO1-WH", "3DP0001 WH",
            "TH0112345678B", "THO1I2345678B", "TH O112345678B", "TH011234S678B", "2410153ABCDEFG")) {
            assertTrue("should pick $s", t.candidates(words(s)).isNotEmpty())
        }
    }

    @Test
    fun picksCodeInsideALine() {
        val t = codes()
        val c = t.candidates(listOf(listOf("LOC:", "A1-02-03")))
        assertEquals(listOf("A1-02-03"), c)
        val d = t.candidates(listOf(listOf("Tracking", "No.", "TH0112345678B")))
        assertTrue(d.contains("TH0112345678B"))
    }

    @Test
    fun skipsNormalWords() {
        val t = codes()
        for (s in listOf("HELLO", "Flash Express", "SOLD OUT", "ราคา 199", "OLD LOG", "Bangkok 10110")) {
            assertTrue("should skip $s: ${t.candidates(words(s))}", t.candidates(words(s)).none { it.startsWith("HELLO") || it == "FLASH EXPRESS" || it == "SOLD OUT" })
        }
        assertFalse(t.looksLikeCode("HELLO"))
        assertFalse(t.looksLikeCode("ราคา"))
    }

    @Test
    fun needsTwoFrames() {
        val t = codes()
        assertTrue(t.confirm(listOf("A1-02-03"), 1000).isEmpty())
        assertEquals(listOf("A1-02-03"), t.confirm(listOf("A1-02-03"), 1100))
        assertTrue(t.confirm(listOf("B2-01-01"), 2000).isEmpty())
        assertTrue("too late", t.confirm(listOf("B2-01-01"), 4000).isEmpty())
    }

    @Test
    fun emptyPatternsMeansBarcodeOnly() {
        val t = TextCodes()
        t.update("{\"patterns\":[]}")
        assertFalse(t.enabled)
        assertTrue(t.candidates(words("A1-02-03")).isEmpty())
        t.update("not json")
        assertFalse(t.enabled)
    }
}
