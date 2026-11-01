"""拍照识别模块给别的模块用的接口（modules.public("recog")，模块关着时拿到 None）。

  match_text(文字, limit=5, types=None)  → [{code, type, conf, src}]  文字容错认码（O/0、I/1、少横杠、一行里还有别的字）
  code_patterns()                        → 手机 App 用来挑「像码的文字」的正则（/api/mobile/code-patterns）
"""
from . import textmatch


def match_text(text, limit=5, types=None):
    return textmatch.match(text, limit, types)


def code_patterns():
    return textmatch.patterns()
