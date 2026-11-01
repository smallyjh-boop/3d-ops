"""识别模块的接口：拍照找产品、拍照读文字、文字容错认码、参考图库、识别测试、手机 App 用的「码的样子」。"""
import json
import os
import time

from flask import Blueprint

from web.common import *  # noqa: F401,F403
from core import modules
from . import descriptor, match, ocr, refs, textmatch

bp = Blueprint("m_recog", __name__)
PREFIXES = ["/api/recog/"]
PATTERNS = []
match.init()
MAX_PHOTO = 15 * 1024 * 1024


def _photo():
    f = request.files.get("photo") or request.files.get("file")
    if not f:
        raise ValueError("没有收到照片")
    raw = f.read(MAX_PHOTO + 1)
    if len(raw) > MAX_PHOTO:
        raise ValueError("照片太大（最多 15 MB）")
    return raw


def _flag(v):
    if v in (None, ""):
        return None
    return str(v).lower() in ("1", "true", "yes", "on")


@bp.post("/api/recog/identify")
def recog_identify():
    try:
        return jsonify(match.identify(_photo(), auth.current_user(), request.form.get("src") or "", _flag(request.form.get("ai"))))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/recog/confirm")
def recog_confirm():
    b = request.get_json(silent=True) or {}
    try:
        return jsonify(match.confirm(str(b.get("rid") or ""), str(b.get("sku") or ""), auth.current_user()))
    except ValueError as e:
        return err(str(e))


@bp.get("/api/recog/search")
def recog_search():
    return jsonify({"items": match.search(request.args.get("q"))})


@bp.get("/api/recog/text")
def recog_text():
    """文字（手机 App 的 ML Kit 认出来的、手输的）→ 系统里最像的码。"""
    q = str(request.args.get("q") or "")[:400]
    if not q.strip():
        return err("没有文字")
    types = set(x for x in (request.args.get("types") or "").split(",") if x) or None
    cands = textmatch.match(q, int(request.args.get("limit") or 5), types)
    thr = match.settings()["threshold"]
    best = cands[0] if cands and cands[0]["conf"] >= max(0.8, thr) and cands[0]["type"] != "location?" else None
    return jsonify({"q": q, "candidates": cands, "best": best})


@bp.post("/api/recog/ocr")
def recog_ocr():
    try:
        raw = _photo()
        r = ocr.read(raw, _flag(request.form.get("ai")))
    except ValueError as e:
        return err(str(e))
    except OSError:
        return err("读不了这张照片（要 JPG / PNG）")
    top = r["candidates"][0] if r["candidates"] else None
    c = db.conn()
    c.execute("INSERT INTO recog_log(rid, at, username, kind, src, top_sku, top_conf, cands, ai_used, ai_ok, text) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (uuid.uuid4().hex[:16], int(time.time()), _uname(), "text", (request.form.get("src") or "")[:20], top["code"] if top else "",
               top["conf"] if top else 0, json.dumps(r["candidates"][:5], ensure_ascii=False), int(r["ai_used"]), int(bool(r["lines"]) and r["ai_used"]),
               "\n".join(r["lines"])[:2000]))
    c.commit()
    thr = match.settings()["threshold"]
    r["best"] = top if top and top["conf"] >= max(0.8, thr) and top["type"] != "location?" else None
    return jsonify(r)


@bp.get("/api/recog/disp/<pid>/<name>")
def recog_disp(pid, name):
    try:
        p = refs.disp_path(pid, name)
    except ValueError:
        p = None
    if not p:
        return err("图片不存在", 404)
    return send_file(p, mimetype="image/jpeg", max_age=3600)


@bp.get("/api/recog/query/<rid>")
def recog_query(rid):
    p = match.query_path(rid)
    if not p:
        return err("照片不存在", 404)
    return send_file(p, mimetype="image/jpeg", max_age=3600)


@bp.get("/api/recog/status")
def recog_status():
    u = auth.current_user() or {}
    ok, why = match.ai_available()
    out = {"settings": match.settings(), "ai": {"available": ok, "why": why}, "ocr_engines": ocr.engines(), "on": match.settings()["on"]}
    if u.get("role") in ("owner", "listing") or not u:
        out.update(refs=refs.status(), usage=match.usage())
    return jsonify(out)


@bp.post("/api/recog/build")
def recog_build():
    b = request.get_json(silent=True) or {}
    pids = [str(x) for x in b.get("pids") or []] or None
    started = refs.start_build(bool(b.get("force")), pids)
    return jsonify({"started": started, "job": dict(refs.JOB)})


@bp.post("/api/recog/model/download")
def recog_model_download():
    """下载小的抠图模型（4.6 MB，GitHub 上 rembg 发布的 u2netp）：照片里的产品抠得更准，识别准很多。"""
    import hashlib
    import requests
    from core.config import DATA_DIR
    d = os.path.join(DATA_DIR, "models")
    os.makedirs(d, exist_ok=True)
    try:
        r = requests.get(descriptor.U2_URL, timeout=120)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return err(f"下载失败：{e}"[:300])
    if hashlib.sha256(r.content).hexdigest() != descriptor.U2_SHA256:
        return err("下载的文件不对（校验不通过），没有保存")
    tmp = os.path.join(d, descriptor.U2_NAME + ".tmp")
    with open(tmp, "wb") as f:
        f.write(r.content)
    os.replace(tmp, os.path.join(d, descriptor.U2_NAME))
    db.audit(_uname(), "识别：下载抠图模型", descriptor.U2_NAME)
    refs.start_build()
    return jsonify({"ok": True, "model": descriptor.model_status()})


@bp.post("/api/recog/test")
def recog_test():
    """识别测试：一张照片（可以带正确的 SKU；文件名用 SKU 开头也行，例如 3DP0001-WH_1.jpg）→ 识别结果和对不对。"""
    try:
        raw = _photo()
    except ValueError as e:
        return err(str(e))
    truth = (request.form.get("truth") or "").strip()
    fname = (request.files.get("photo") or request.files.get("file")).filename or ""
    if not truth and fname:
        stem = os.path.splitext(os.path.basename(fname))[0]
        ix = refs.index()
        for cut in (stem, stem.split("_")[0], stem.split(" ")[0]):
            if cut.upper() in {s.upper() for s in ix.get("skus", {})}:
                truth = next(s for s in ix["skus"] if s.upper() == cut.upper())
                break
    try:
        r = match.identify(raw, auth.current_user(), "test", _flag(request.form.get("ai")), truth)
    except ValueError as e:
        return err(str(e))
    skus = [c["sku"] for c in r["candidates"]]
    r["truth"] = truth
    r["rank"] = (skus.index(truth) + 1) if truth in skus else (0 if truth else None)
    r["truth_info"] = match.sku_info(truth) if truth else None
    return jsonify(r)


@bp.get("/api/recog/recent")
def recog_recent():
    return jsonify({"rows": match.recent(int(request.args.get("n") or 50))})
