"""拍照找产品：第一步本地比特征（快、不花钱）取前 8 个候选；第二步（可选）把照片和 8 个候选拼成一张图给 ERP 的 AI 看，
让它挑最像的那个并给出把握。AI 不能看图（例如 DeepSeek）、关掉了、今天的次数用完了 → 只用第一步。

结果给手机 / 电脑页面：前 3 个（带图、把握），把握不够或者前两个差不多时让员工自己点（「都不是」→ 手动搜）。
员工点了「就是它」→ confirm()：记下来，照片存成这个 SKU 的参考图（越用越准）。
"""
import base64
import io
import json
import os
import re
import threading
import time
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core import db, store
from core.config import DATA_DIR, load_config

from . import descriptor as D
from . import refs

QDIR = os.path.join(DATA_DIR, "recog", "queries")
KEEP_QUERIES = 600
TOP_N = 8
SCHEMA = """
CREATE TABLE IF NOT EXISTS recog_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, rid TEXT UNIQUE, at INTEGER, username TEXT, kind TEXT, src TEXT,
  top_sku TEXT, top_conf REAL, cands TEXT, ai_used INTEGER DEFAULT 0, ai_ok INTEGER DEFAULT 0, ai_pick TEXT, ai_note TEXT,
  chosen TEXT, chosen_at INTEGER, truth TEXT, ms INTEGER, text TEXT
);
CREATE INDEX IF NOT EXISTS ix_recog_log_at ON recog_log(at);
"""
_no_vision = {"until": 0, "why": ""}
_lock = threading.Lock()


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(recog_log)")}
    if "learned" not in cols:                 # 1.1：这次确认存成了哪张参考照片（撤销用）
        c.execute("ALTER TABLE recog_log ADD COLUMN learned TEXT")
    c.commit()


# ---------------- 设置 ----------------
def settings(cfg=None):
    cfg = cfg or load_config()
    try:
        thr = float(cfg.get("recog_threshold") or 0.75)
    except (TypeError, ValueError):
        thr = 0.75
    try:
        cap = int(cfg.get("recog_ai_daily") or 0)
    except (TypeError, ValueError):
        cap = 0
    return {"on": bool(cfg.get("recog_on", True)), "ai": str(cfg.get("recog_ai") or "auto"), "threshold": min(0.99, max(0.3, thr)),
            "ai_daily": cap, "learn": bool(cfg.get("recog_learn", True)), "ocr_ai": bool(cfg.get("recog_ocr_ai", True))}


def ai_available(cfg=None):
    """(能不能用 AI 看图, 原因)。"""
    cfg = cfg or load_config()
    s = settings(cfg)
    if s["ai"] == "off":
        return False, "设置里关了 AI 看图"
    if not (cfg.get("ai_api_key") or "").strip():
        return False, "还没有填写 AI 接口密钥"
    if s["ai"] == "auto" and str(cfg.get("ai_provider") or "anthropic") == "deepseek":
        return False, "现在的 AI（DeepSeek）不能看图，只用本地比对"
    if _no_vision["until"] > time.time():
        return False, _no_vision["why"]
    if s["ai_daily"] > 0 and usage()["today_ai"] >= s["ai_daily"]:
        return False, "今天的 AI 看图次数用完了"
    return True, ""


def usage():
    c = db.conn()
    t0 = int(time.time()) - 86400
    t30 = int(time.time()) - 30 * 86400
    row = lambda q, a: c.execute(q, a).fetchone()[0] or 0  # noqa: E731
    return {"today": row("SELECT COUNT(*) FROM recog_log WHERE at>=?", (t0,)),
            "today_ai": row("SELECT COUNT(*) FROM recog_log WHERE at>=? AND ai_used=1", (t0,)),
            "d30": row("SELECT COUNT(*) FROM recog_log WHERE at>=?", (t30,)),
            "d30_ai": row("SELECT COUNT(*) FROM recog_log WHERE at>=? AND ai_used=1", (t30,)),
            "d30_confirmed": row("SELECT COUNT(*) FROM recog_log WHERE at>=? AND chosen IS NOT NULL AND kind='product'", (t30,)),
            "d30_top1": row("SELECT COUNT(*) FROM recog_log WHERE at>=? AND chosen IS NOT NULL AND chosen=top_sku AND kind='product'", (t30,))}


# ---------------- 候选的资料 ----------------
_pcache = {}


def _product(pid):
    try:
        mt = os.path.getmtime(os.path.join(store.PRODUCTS_DIR, store.safe_id(pid) + ".json"))
    except (OSError, ValueError):
        return None
    hit = _pcache.get(pid)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        p = store.load(pid)
    except Exception:  # noqa: BLE001
        return None
    _pcache[pid] = (mt, p)
    return p


def sku_info(sku, pid=None):
    ix = refs.index()
    pid = pid or ix.get("skus", {}).get(sku) or str(sku).split("-")[0]
    p = _product(pid)
    if not p:
        return None
    v = next((x for x in p.get("variants") or [] if str(x.get("sku")) == str(sku)), None)
    if v is None:
        return None
    d = ix.get("disp", {}).get(sku)
    img = f"/api/recog/disp/{pid}/{d[1]}" if d else ""
    if not img:
        from modules.mobile import resolver
        vi = (p.get("variants") or []).index(v)
        img = resolver._img_of(p, vi)
    return {"sku": str(sku), "product_id": p["id"], "name_zh": p.get("name_zh") or "", "title_th": (p.get("copy") or {}).get("title_th") or "",
            "opt1_zh": v.get("opt1_zh") or "", "opt2_zh": v.get("opt2_zh") or "", "img": img, "weak": weak_kind(v.get("opt1_zh"))}


# 照片认不准的颜色：随机色（实物什么颜色都有）、多色 / 彩虹（颜色分布不固定）、透明（拍出来是背景的颜色）
WEAK = {"RND": "random", "MC": "multi", "RB": "multi", "CL": "clear"}


def weak_kind(color_name):
    from core import codes
    row = codes.find_color(load_config(), color_name) if color_name else None
    return WEAK.get(row[1], "") if row else ""


# ---------------- 第一步：本地比对 ----------------
def rank(qvec, ix=None, n=TOP_N, weights=None):
    """→ [(sku, 分数, 第几张参考图)]（同一个 SKU 取最像的那张）。"""
    ix = ix or refs.index()
    V = ix["vecs"]
    if not len(V):
        return []
    w = weights or D.WEIGHTS
    score = None
    for q in np.atleast_2d(qvec):                             # 照片的几种「假设」（describe_query）：每张参考图取最像的
        sims = D.part_sims(q, V)
        col = np.where(ix["colw"] > 0, sims["col"], 0.55)     # 没颜色的参考图（灰色 3D 图）颜色按一般算
        sc = (w["col"] * col + w["shp"] * sims["shp"] + w["geo"] * sims["geo"] + w["edg"] * sims["edg"]) / sum(w.values())
        score = sc if score is None else np.maximum(score, sc)
    best = {}
    for i in np.argsort(-score)[:max(400, n * 40)]:
        for s in ix["meta"][i]["skus"]:
            if s not in best:
                best[s] = (float(score[i]), int(i))
        if len(best) >= n * 3:
            break
    out = sorted(((s, sc, i) for s, (sc, i) in best.items()), key=lambda x: -x[1])
    return out[:n]


def confidence(ranked, lo=0.55, span=0.35, gap=0.05):
    """第一步自己的把握（0..1）：分数高、和第二名拉得开才有把握（参数按 eval_recog.py 的测试数据粗略校准）。"""
    if not ranked:
        return []
    s1 = ranked[0][1]
    s2 = ranked[1][1] if len(ranked) > 1 else s1 - gap
    out = []
    for k, (_s, sc, _i) in enumerate(ranked):
        absq = float(np.clip((sc - lo) / span, 0, 1))
        if k == 0:
            g = float(np.clip((s1 - s2) / gap, 0, 1))
        else:
            g = float(np.clip(1 - (s1 - sc) / gap, 0, 1)) * 0.5
        out.append(round(0.5 * absq + 0.5 * g, 3))
    return out


# ---------------- 第二步：AI 看图 ----------------
def _font(n):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, n)
        except OSError:
            continue
    return ImageFont.load_default()


def _tile(im, s):
    im = im.convert("RGBA") if im.mode != "RGBA" else im
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, (0, 0), im)
    bg.thumbnail((s, s))
    t = Image.new("RGB", (s, s), (255, 255, 255))
    t.paste(bg, ((s - bg.width) // 2, (s - bg.height) // 2))
    return t


def contact_sheet(photo, cands):
    """左边大图 = 员工拍的照片；右边 2 行 × 4 个 = 候选（左上角编号 1~8）。"""
    S, B = 240, 480
    W = B + 4 * S + 50
    H = max(B, 2 * S) + 40
    sheet = Image.new("RGB", (W, H), (235, 235, 235))
    d = ImageDraw.Draw(sheet)
    f = _font(30)
    sheet.paste(_tile(photo, B), (10, 30))
    d.text((14, 0), "PHOTO", fill=(200, 0, 0), font=_font(24))
    for k, (_sku, im) in enumerate(cands[:8]):
        x = B + 20 + (k % 4) * (S + 5)
        y = 30 + (k // 4) * (S + 5)
        sheet.paste(_tile(im, S), (x, y))
        d.rectangle([x, y, x + 40, y + 38], fill=(20, 20, 20))
        d.text((x + 10, y + 2), str(k + 1), fill=(255, 255, 0), font=f)
    return sheet


def _cand_image(sku, info):
    ix = refs.index()
    d = ix.get("disp", {}).get(sku)
    fp = refs.disp_path(*d) if d else None
    if not fp and info and info.get("img", "").startswith("/files/"):
        parts = info["img"].split("/")
        fp = os.path.join(store.product_dir(parts[2]), parts[3], parts[4])
    try:
        return Image.open(fp) if fp and os.path.isfile(fp) else Image.new("RGB", (200, 200), (250, 250, 250))
    except Exception:  # noqa: BLE001
        return Image.new("RGB", (200, 200), (250, 250, 250))


AI_SYSTEM = ("You identify physical products (3D-printed items) from a staff phone photo. Compare shape first, then colour. "
             "Candidates may be renders or product photos, so ignore background, lighting and small colour shifts. Output only JSON.")


def ai_pick(photo, cands, call=None):
    """cands: [(sku, info)]。返回 {pick: 第几个(1..8) 或 0, confidence, reason}；出错抛 RuntimeError。"""
    from core import ai_copy
    cfg = load_config()
    lines = []
    for k, (sku, info) in enumerate(cands, 1):
        lines.append(f"{k}. SKU {sku}: {(info or {}).get('name_zh', '')} {(info or {}).get('opt1_zh', '')} {(info or {}).get('opt2_zh', '')}".strip())
    user = ("The big image on the left (PHOTO) was taken by a staff member. On the right are numbered candidate products:\n"
            + "\n".join(lines) +
            "\nWhich candidate is the same product as the PHOTO (same shape AND same colour/variant)? If none matches, pick 0.\n"
            'Reply JSON: {"pick": <0-8>, "confidence": <0.0-1.0>, "second": <0-8 or 0>, "reason": "<short, Chinese>", "reason_th": "<the same in Thai>"}')
    sheet = contact_sheet(photo, [(s, _cand_image(s, i)) for s, i in cands])
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=82)
    b64 = base64.b64encode(buf.getvalue()).decode()
    fn = call or ai_copy._request          # 直接用 _request：不让它在看不了图时悄悄退回纯文字（那样 AI 会瞎猜）
    try:
        txt = fn(cfg, AI_SYSTEM, user, b64)
    except ai_copy.AIError as e:
        msg = str(e)
        if re.search(r"\b(400|404|415|422)\b", msg) and re.search(r"image|vision|multimodal|content", msg, re.I):
            _no_vision.update(until=time.time() + 3600, why="现在的 AI 模型不能看图（1 小时后再试）")
        raise RuntimeError(msg) from e
    d = ai_copy.extract_json(txt)
    try:
        pick = int(d.get("pick") or 0)
    except (TypeError, ValueError):
        pick = 0
    try:
        conf = float(d.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    try:
        second = int(d.get("second") or 0)
    except (TypeError, ValueError):
        second = 0
    return {"pick": pick if 0 <= pick <= len(cands) else 0, "confidence": max(0.0, min(1.0, conf)),
            "second": second if 0 < second <= len(cands) else 0, "reason": str(d.get("reason") or "")[:200],
            "reason_th": str(d.get("reason_th") or "")[:300]}


# ---------------- 整个流程 ----------------
def _save_query(raw, rid):
    os.makedirs(QDIR, exist_ok=True)
    im = D.open_image(raw).convert("RGB")
    im.thumbnail((1000, 1000))
    im.save(os.path.join(QDIR, rid + ".jpg"), "JPEG", quality=85)
    files = sorted(os.listdir(QDIR))
    if len(files) > KEEP_QUERIES:
        olds = sorted(files, key=lambda n: os.path.getmtime(os.path.join(QDIR, n)))[:len(files) - KEEP_QUERIES]
        for n in olds:
            try:
                os.remove(os.path.join(QDIR, n))
            except OSError:
                pass
    return im


def query_path(rid):
    if not re.fullmatch(r"[0-9a-f]{12,32}", str(rid or "")):
        return None
    p = os.path.join(QDIR, rid + ".jpg")
    return p if os.path.isfile(p) else None


def identify(raw, user=None, src="", use_ai=None, truth="", ai_call=None):
    """照片 → {rid, candidates[...], top, need_pick, ai{...}, stage, ms}。"""
    t0 = time.time()
    s = settings()
    if not s["on"]:
        raise ValueError("产品识别在设置里关掉了")
    if not raw:
        raise ValueError("没有收到照片")
    rid = uuid.uuid4().hex[:16]
    try:
        im = _save_query(raw, rid)
    except Exception as e:  # noqa: BLE001
        raise ValueError("读不了这张照片（要 JPG / PNG）") from e
    ix = refs.index()
    if not len(ix["vecs"]):
        if not refs.JOB["running"]:
            refs.start_build()
        raise ValueError("识别图还没建好：系统正在后台生成（产品多时要几分钟），请稍后再试")
    q = D.describe_query(im)
    ranked = rank(q, ix)
    confs = confidence(ranked)
    cands = []
    for (sku, sc, i), cf in zip(ranked, confs):
        info = sku_info(sku, ix["meta"][i]["pid"])
        if info:
            cands.append({**info, "score": round(sc, 4), "conf": cf, "via": ix["meta"][i]["kind"]})
    ai = {"used": False, "ok": False, "why": ""}
    ok_ai, why = ai_available()
    if use_ai is False:
        ok_ai, why = False, "这次不用 AI"
    if ok_ai and cands:
        ai["used"] = True
        try:
            r = ai_pick(im, [(c["sku"], c) for c in cands[:TOP_N]], ai_call)
            ai.update(ok=True, **r)
            if r["pick"]:
                k = r["pick"] - 1
                chosen = cands.pop(k)
                chosen["conf"] = round(max(r["confidence"], 0.0), 3)
                chosen["ai"] = True
                cands.insert(0, chosen)
                if r.get("second"):
                    sec_sku = None
                    order = [c["sku"] for c in cands]
                    # second 是 AI 看到的编号（原来的顺序）
                    orig = [x[0] for x in ranked]
                    if 0 < r["second"] <= len(orig):
                        sec_sku = orig[r["second"] - 1]
                    if sec_sku and sec_sku in order and order.index(sec_sku) > 1:
                        cands.insert(1, cands.pop(order.index(sec_sku)))
                for c in cands[1:]:
                    c["conf"] = round(min(c["conf"], max(0.0, 1 - chosen["conf"]) + 0.05), 3)
            else:
                for c in cands:
                    c["conf"] = round(min(c["conf"], 0.3), 3)
        except Exception as e:  # noqa: BLE001  AI 出错：只用第一步
            ai.update(ok=False, why=str(e)[:200])
    else:
        ai["why"] = why
    top = cands[0] if cands else None
    weak = sorted({c["weak"] for c in cands[:3] if c.get("weak")})
    hint = None
    if weak:                                   # 随机色 / 多色 / 透明的规格：颜色靠不住，一定让员工自己看清楚再点
        hint = {"kinds": weak, "zh": "前几个里有随机色 / 多色 / 透明的规格：照片认颜色不可靠，请对一下实物再点",
                "th": "ใน 3 อันดับแรกมีแบบสีสุ่ม / หลายสี / ใส: ดูสีจากรูปไม่แม่น กรุณาเทียบกับของจริงก่อนกด"}
    need_pick = bool(weak) or (not top or top["conf"] < s["threshold"]
                 or (len(cands) > 1 and not top.get("ai") and cands[1]["product_id"] != top["product_id"] and cands[1]["score"] > top["score"] - 0.015))
    ms = int((time.time() - t0) * 1000)
    c = db.conn()
    c.execute("INSERT INTO recog_log(rid, at, username, kind, src, top_sku, top_conf, cands, ai_used, ai_ok, ai_pick, ai_note, truth, ms) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (rid, int(time.time()), (user or {}).get("username") or "", "product", src[:20], top["sku"] if top else "", top["conf"] if top else 0,
               json.dumps([[x["sku"], x["score"], x["conf"]] for x in cands[:8]]), int(ai["used"]), int(ai["ok"]),
               str(ai.get("pick") or ""), (ai.get("reason") or ai.get("why") or "")[:200], truth or None, ms))
    c.commit()
    return {"rid": rid, "candidates": cands[:TOP_N], "top": top, "need_pick": bool(need_pick), "hint": hint, "ai": ai, "threshold": s["threshold"],
            "ms": ms, "photo": f"/api/recog/query/{rid}"}


def confirm(rid, sku, user=None, learn=None):
    """员工点了「就是它」（sku 空 = 都不是）。照片存成参考图（设置里可以关）。同一次识别再确认（撤销后重选）：先删掉上次存的照片。"""
    c = db.conn()
    r = c.execute("SELECT * FROM recog_log WHERE rid=?", (rid,)).fetchone()
    if not r:
        raise ValueError("这次识别的记录找不到了")
    _forget(r)
    c.execute("UPDATE recog_log SET chosen=?, chosen_at=?, learned=NULL WHERE rid=?", (sku or "", int(time.time()), rid))
    c.commit()
    learned = ""
    if sku and r["kind"] == "product" and (settings()["learn"] if learn is None else learn):
        info = sku_info(sku)
        fp = query_path(rid)
        if info and fp:
            with open(fp, "rb") as f:
                fn = refs.add_photo(info["product_id"], sku, f.read())
            learned = f"{info['product_id']}/{fn}"
            c.execute("UPDATE recog_log SET learned=? WHERE rid=?", (learned, rid))
            c.commit()
    return {"ok": True, "learned": bool(learned)}


def _forget(r):
    if r["learned"] if "learned" in r.keys() else None:
        pid, fn = r["learned"].split("/", 1)
        try:
            refs.delete_learned(pid, fn)
        except ValueError:
            pass


UNDO_SECONDS = 600


def unconfirm(rid, user=None):
    """刚才点错了：撤销这次确认（删掉存成参考图的照片）。员工只能撤销自己 10 分钟内的；老板 / 上架都可以。"""
    c = db.conn()
    r = c.execute("SELECT * FROM recog_log WHERE rid=?", (rid,)).fetchone()
    if not r:
        raise ValueError("这次识别的记录找不到了")
    u = user or {}
    if u.get("role") not in ("owner", "listing"):
        if r["username"] != u.get("username") or time.time() - (r["chosen_at"] or 0) > UNDO_SECONDS:
            raise ValueError("只能撤销自己 10 分钟内的确认")
    _forget(r)
    c.execute("UPDATE recog_log SET chosen=NULL, chosen_at=NULL, learned=NULL WHERE rid=?", (rid,))
    c.commit()
    return {"ok": True}


def search(q, limit=20):
    """「都不是」→ 手动搜产品：SKU / 名称 / 泰文标题。"""
    q = str(q or "").strip().lower()
    if len(q) < 1:
        return []
    out = []
    for name in sorted(os.listdir(store.PRODUCTS_DIR)) if os.path.isdir(store.PRODUCTS_DIR) else []:
        if not name.endswith(".json"):
            continue
        p = _product(name[:-5])
        if not p:
            continue
        hay = " ".join([p["id"], p.get("name_zh") or "", (p.get("copy") or {}).get("title_th") or ""]).lower()
        for v in p.get("variants") or []:
            h2 = hay + " " + " ".join(str(v.get(k) or "") for k in ("sku", "opt1_zh", "opt2_zh")).lower()
            if all(t in h2 for t in q.split()):
                info = sku_info(v.get("sku"), p["id"])
                if info:
                    out.append(info)
            if len(out) >= limit:
                return out
    return out


def recent(limit=50):
    rows = db.conn().execute("SELECT * FROM recog_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
