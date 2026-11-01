"""拍照读文字（货位牌、面单、标签）：照片 → 条码 + 文字 → 系统里的码（textmatch 容错匹配）。

条码：zxing-cpp（requirements 里已经有）在照片里找条码 / 二维码，读到的直接认（条码坏了也没关系，还有文字）。
文字（按顺序用第一个能用的）：
  rapidocr   本地 OCR（pip install rapidocr_onnxruntime，要 onnxruntime + opencv；中英文、CPU 上一张 0.3~1 秒）
  tesseract  本地 OCR（系统装了 tesseract 命令）
  ai         ERP 的 AI 看图（要能看图的 AI；算一次 AI 调用）
都没有 → 只读条码。手机 App 自己用 ML Kit 认文字，不走这里（结果一样送到 /api/recog/text）。
"""
import base64
import io
import shutil
import subprocess
import tempfile
import os

from PIL import Image, ImageOps

from core.config import load_config

from . import textmatch

_rapid = {"eng": None, "err": ""}


def engines():
    out = []
    try:
        import importlib.util
        if importlib.util.find_spec("rapidocr_onnxruntime"):
            out.append("rapidocr")
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("tesseract"):
        out.append("tesseract")
    return out


def _img(raw):
    im = Image.open(io.BytesIO(raw))
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:  # noqa: BLE001
        pass
    im = im.convert("RGB")
    if max(im.size) > 1600:
        im.thumbnail((1600, 1600))
    return im


def barcodes(im):
    try:
        import zxingcpp
    except Exception:  # noqa: BLE001
        return []
    out = []
    for g in (im, ImageOps.autocontrast(im.convert("L"))):
        try:
            for r in zxingcpp.read_barcodes(g):
                t = (r.text or "").strip()
                if t and t not in out:
                    out.append(t)
        except Exception:  # noqa: BLE001
            continue
        if out:
            break
    return out


def _rapidocr(im):
    if _rapid["eng"] is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapid["eng"] = RapidOCR()
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    res, _t = _rapid["eng"](buf.getvalue())
    return [str(x[1]) for x in res or []]


def _tesseract(im):
    with tempfile.TemporaryDirectory() as d:
        fp = os.path.join(d, "x.png")
        ImageOps.autocontrast(im.convert("L")).save(fp)
        r = subprocess.run(["tesseract", fp, "stdout", "--psm", "11"], capture_output=True, text=True, timeout=30)
        return [x for x in r.stdout.splitlines() if x.strip()]


OCR_SYSTEM = "You are an OCR engine for a warehouse. Read text exactly as printed; do not translate or correct. Output only JSON."
OCR_USER = ("Read every piece of text in this photo (location signs like A1-02-03, order numbers, tracking numbers, SKUs like 3DP0001-WH, "
            "labels in Chinese or Thai, and the human-readable digits printed under barcodes). One entry per line of text.\n"
            'Reply JSON: {"lines": ["..."]}')


def _ai(im, call=None):
    from core import ai_copy
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    fn = call or ai_copy._request
    txt = fn(ai_copy.tcfg(load_config(), "ocr"), OCR_SYSTEM, OCR_USER, base64.b64encode(buf.getvalue()).decode())
    d = ai_copy.extract_json(txt)
    return [str(x) for x in d.get("lines") or [] if str(x).strip()]


def read(raw, use_ai=None, ai_call=None, engine=None):
    """照片 → {barcodes, lines, engine, candidates, error}。"""
    from . import match
    im = _img(raw)
    bc = barcodes(im)
    lines, eng, error = [], "", ""
    order = [engine] if engine else engines()
    for e in order:
        try:
            lines = _rapidocr(im) if e == "rapidocr" else _tesseract(im) if e == "tesseract" else []
            eng = e
            if lines:
                break
        except Exception as ex:  # noqa: BLE001  装了但用不了：试下一个
            error = f"{e}: {ex}"[:200]
    ai_used = False
    if not lines and engine is None:
        ok, why = match.ai_available()
        s = match.settings()
        if use_ai is False or not s["ocr_ai"]:
            ok, why = False, why or "设置里关了 AI 读文字"
        if ok:
            ai_used = True
            try:
                lines = _ai(im, ai_call)
                eng = "ai"
            except Exception as ex:  # noqa: BLE001
                error = str(ex)[:200]
        elif not bc:
            error = error or why or "没有能用的文字识别（装 rapidocr，或者用能看图的 AI）"
    cands = []
    for b in bc:                                      # 条码：完全一样的最可信
        for c in textmatch.match(b, 3):
            c = dict(c, src="barcode:" + b)
            if textmatch.canon(c["code"]) == textmatch.canon(b):
                c["conf"] = 1.0
            cands.append(c)
    cands += textmatch.match("\n".join(lines), 8)
    best = {}
    for c in cands:
        if c["code"] not in best or best[c["code"]]["conf"] < c["conf"]:
            best[c["code"]] = c
    out = sorted(best.values(), key=lambda x: -x["conf"])[:8]
    return {"barcodes": bc, "lines": lines[:60], "engine": eng, "ai_used": ai_used, "candidates": out, "error": error}
