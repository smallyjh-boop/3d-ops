"""文字 → 系统里的码（货位、订单号、快递单号、SKU、物品编码），容忍文字识别常见的错。

文字识别（手机 App 的 ML Kit、AI 看照片、tesseract）常见的错：
  O / 0 / Q / D 分不清，I / 1 / l / | 分不清，S / 5，B / 8，Z / 2，G / 6；少了「-」、多了空格；
  一行里还有别的字（「LOC: A1-02-03」「Order No. 2410…」）；长单号读错一两个字。
做法：
  1. 把文字切成词，再把相邻 1~3 个词拼起来（「A1 02 03」）。
  2. 每个词算「骨架」：大写、去掉符号、易混的字换成同一个（O→0、I→1、S→5、B→8、Z→2、G→6）。
  3. 和系统里所有的码比：完全一样 1.0；骨架一样 0.93；包含 0.9；骨架差 1~2 个字（长码）0.85→0.6。
  4. 货位编号即使系统里没有，也按格式整理成标准写法（a1 2 3 → A1-02-03）给出来（置信度低一点）。
对外：match(text, limit=5) → [{code, type, conf, src}]；patterns() → 手机 App 用来挑「像码的文字」的正则。
"""
import re
import threading
import time

from core import db, modules

SKEL = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1", "!": "1", "S": "5", "B": "8", "Z": "2", "G": "6"})
CONFUSE = {"0": "OQD", "1": "IL|", "5": "S", "8": "B", "2": "Z", "6": "G", "O": "0Q", "Q": "0O", "D": "0", "I": "1L", "L": "1I",
           "S": "5", "B": "8", "Z": "2", "G": "6"}
_NON = re.compile(r"[^0-9A-Z]")
LOC_LOOSE = re.compile(r"^([A-Z8]{1,2})[\s\-_./:]*([0-9OQDILSBZ|]{1,2})[\s\-_./:]+([0-9OQDILSBZ|]{1,2})[\s\-_./:]+([0-9OQDILSBZ|]{1,2})$")
LOC_TIGHT = re.compile(r"^([A-Z])([0-9OQDILSBZ|])([0-9OQDILSBZ|]{2})([0-9OQDILSBZ|]{2})$")     # A10203（没有横杠）
TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1", "S": "5", "B": "8", "Z": "2", "G": "6"})
TO_LETTER = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"})

TTL = 60
_cache = {"at": 0.0, "codes": None}
_lock = threading.Lock()


def canon(s):
    return _NON.sub("", str(s or "").upper().replace("|", "I").replace("!", "I"))


def skel(s):
    return canon(s).translate(SKEL)


def lev(a, b, cap=3):
    """编辑距离（超过 cap 就停）。"""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            best = min(best, cur[j])
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


# ---------------- 系统里有哪些码 ----------------
def _load_codes():
    """[(码, 类型)]：货位、货架、物品编码、SKU、最近的订单号 / 快递单号。"""
    out = []
    c = db.conn()
    if modules.enabled("inv"):
        try:
            for r in c.execute("SELECT code FROM inv_locations WHERE active=1"):
                out.append((r["code"], "location"))
            for r in c.execute("SELECT code, name FROM inv_loc_groups"):
                out.append((r["code"], "shelf" if len(r["code"]) > 1 or r["code"][-1:].isdigit() else "zone"))
                if (r["name"] or "").strip():
                    out.append((r["name"].strip(), "label:" + r["code"]))
        except Exception:  # noqa: BLE001  库存模块的表还没建
            pass
        try:
            for r in c.execute("SELECT code FROM inv_items WHERE active=1"):
                out.append((r["code"], "item"))
        except Exception:  # noqa: BLE001
            pass
    try:
        from core import store
        import json
        import os
        for name in os.listdir(store.PRODUCTS_DIR):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(store.PRODUCTS_DIR, name), encoding="utf-8") as f:
                    p = json.load(f)
            except (OSError, ValueError):
                continue
            for v in p.get("variants") or []:
                if v.get("sku"):
                    out.append((str(v["sku"]), "sku"))
    except OSError:
        pass
    since = int(time.time()) - 120 * 86400
    for r in c.execute("SELECT order_no, tracking_no FROM orders WHERE COALESCE(order_time, imported_at, 0) >= ? OR status IN ('to_ship','unpaid') "
                       "ORDER BY id DESC LIMIT 20000", (since,)):
        if r["order_no"]:
            out.append((r["order_no"], "order"))
        if r["tracking_no"]:
            out.append((r["tracking_no"], "tracking"))
    return out


def _index():
    with _lock:
        if _cache["codes"] is not None and time.time() - _cache["at"] < TTL:
            return _cache
        codes = _load_codes()
        by_canon, by_skel, grams, labels = {}, {}, {}, []
        for code, typ in codes:
            if typ.startswith("label:"):
                labels.append((code, typ[6:]))
                continue
            k = canon(code)
            if len(k) < 2:
                continue
            by_canon.setdefault(k, (code, typ))
            sk = k.translate(SKEL)
            by_skel.setdefault(sk, []).append((code, typ))
            for i in range(len(sk) - 2):
                grams.setdefault(sk[i:i + 3], set()).add(sk)
        _cache.update(at=time.time(), codes=codes, by_canon=by_canon, by_skel=by_skel, grams=grams, labels=labels)
        return _cache


def invalidate():
    with _lock:
        _cache["codes"] = None


# ---------------- 切词 ----------------
def tokens(text):
    """一段识别出来的文字 → 候选词（单个词、相邻 2~3 个词拼起来、整行）。"""
    out = []
    for line in re.split(r"[\r\n]+", str(text or "")):
        line = line.strip()
        if not line:
            continue
        # 「订单号: 123」「LOC：A1-02-03」：冒号后面的也单独算
        parts = [p for p in re.split(r"[\s,;，；、]+|(?<=[:：])", line) if p.strip(" :：")]
        parts = [p.strip(" :：#") for p in parts]
        for i in range(len(parts)):
            for n in (1, 2, 3):
                if i + n <= len(parts):
                    out.append(" ".join(parts[i:i + n]))
        out.append(line)
    seen, res = set(), []
    for t in out:
        if t and t not in seen:
            seen.add(t)
            res.append(t)
    return res[:400]


def loc_guess(tok):
    """看起来像货位编号就整理成标准写法（系统里没有也给）。"""
    s = str(tok or "").strip().upper()
    m = LOC_LOOSE.match(s) or LOC_TIGHT.match(_NON.sub("", s))
    if not m:
        return None
    zone = m.group(1).translate(TO_LETTER)
    nums = [m.group(i).translate(TO_DIGIT) for i in (2, 3, 4)]
    if not all(x.isdigit() for x in nums) or not zone.isalpha():
        return None
    a, b, c = (int(x) for x in nums)
    if not (1 <= a <= 99 and 1 <= b <= 99 and 1 <= c <= 99):
        return None
    return f"{zone}{a}-{b:02d}-{c:02d}"


# ---------------- 匹配 ----------------
def match(text, limit=5, types=None):
    """返回 [{code, type, conf, src}]（按置信度从高到低，同一个码只出现一次）。types：只要这些类型（例如 {"location"}）。"""
    ix = _index()
    best = {}

    def add(code, typ, conf, src):
        if types and typ not in types:
            return
        k = (code, typ)
        if k not in best or best[k]["conf"] < conf:
            best[k] = {"code": code, "type": typ, "conf": round(float(conf), 3), "src": src}

    toks = tokens(text)
    for t in toks:
        k = canon(t)
        if len(k) < 2:
            continue
        if k in ix["by_canon"]:
            code, typ = ix["by_canon"][k]
            add(code, typ, 1.0 if len(k) >= 4 else 0.8, t)
        sk = k.translate(SKEL)
        for code, typ in ix["by_skel"].get(sk, []):
            if canon(code) != k:
                add(code, typ, 0.93 if len(sk) >= 5 else 0.75, t)
        g = loc_guess(t)
        if g:
            hit = ix["by_canon"].get(canon(g))
            if hit:
                add(hit[0], hit[1], 0.95, t)
            else:
                add(g, "location?", 0.55, t)
        if len(sk) >= 6:
            # 骨架包含：一行里还有别的字
            cands = {}
            for i in range(len(sk) - 2):
                for c_ in ix["grams"].get(sk[i:i + 3], ()):
                    cands[c_] = cands.get(c_, 0) + 1
            for c_, n in cands.items():
                if n < max(2, (len(c_) - 2) // 3):
                    continue
                if len(c_) >= 6 and c_ in sk and c_ != sk:
                    for code, typ in ix["by_skel"][c_]:
                        add(code, typ, 0.9 if len(c_) >= 8 else 0.8, t)
                    continue
                if abs(len(c_) - len(sk)) <= 2 and len(c_) >= 6:
                    d = lev(sk, c_, 2)
                    if d <= (1 if len(c_) < 10 else 2):
                        for code, typ in ix["by_skel"][c_]:
                            add(code, typ, (0.85 if d == 1 else 0.7) - (0.05 if len(c_) < 8 else 0), t)
    # 货位牌上的中文 / 泰文名字（例如「成品区」）
    low = str(text or "").lower()
    for name, code in ix["labels"]:
        if len(name) >= 2 and name.lower() in low:
            add(code, "shelf", 0.8, name)
    out = sorted(best.values(), key=lambda x: (-x["conf"], x["type"] == "location?", len(x["code"])))
    seen, res = set(), []
    for x in out:
        if x["code"] in seen:
            continue
        seen.add(x["code"])
        res.append(x)
    # 前两个一样像（例如读错一个字，3DP0001 / 3DP0011 都只差一个字）：不能自动用，让人点
    if len(res) > 1 and res[0]["conf"] < 1.0 and res[1]["conf"] >= res[0]["conf"] - 0.02:
        for x in res[:2]:
            x["conf"] = min(x["conf"], 0.7)
            x["tie"] = True
    return res[:limit]


# ---------------- 给手机 App 的正则 ----------------
def _shape(code):
    """码的「样子」：TH5566778899 → [('L',2),('D',10)]（字母 / 数字 / 横杠的段）。"""
    out = []
    for ch in str(code):
        k = "D" if ch.isdigit() else "L" if ch.isalpha() else "-" if ch in "-_" else "?"
        if out and out[-1][0] == k:
            out[-1][1] += 1
        else:
            out.append([k, 1])
    return tuple((k, n) for k, n in out)


def _rx(shape):
    """样子 → 宽松的正则（数字位置也认 O/I/S/B…；横杠可有可无）。"""
    parts = []
    for k, n in shape:
        if k == "D":
            parts.append(f"[0-9OQDILSBZ|]{{{n}}}")
        elif k == "L":
            parts.append(f"[A-Z0-9]{{{n}}}")
        elif k == "-":
            parts.append("[-_ ]?")
        else:
            return None
    return "^" + "".join(parts) + "$"


def patterns():
    """手机 App 文字识别用：哪些文字「像码」（像了才送给网页，网页再问服务器 /api/recog/text 认是哪个）。"""
    from core.config import load_config
    cfg = load_config()
    pre = re.sub(r"[^A-Z0-9]", "", str(cfg.get("sku_prefix") or "3DP").upper()) or "3DP"
    pre_rx = "".join("[" + re.escape(ch + CONFUSE.get(ch, "")) + "]" for ch in pre)
    pats = [
        {"type": "location", "re": r"^[A-Z8]{1,2}[0-9OQDILSBZ|]{1,2}[-_ .]{0,2}[0-9OQDILSBZ|]{1,2}[-_ .]{0,2}[0-9OQDILSBZ|]{1,2}$"},
        {"type": "sku", "re": "^" + pre_rx + r"[-_ ]?[0-9OQDILSBZ|]{4}([-_ ]?[A-Z0-9]{1,5}){0,2}$"},
    ]
    seen = set()
    ix = _index()
    counts = {}
    for code, typ in ix["codes"] or []:
        if typ in ("order", "tracking", "item", "sku") and len(canon(code)) >= 6:
            sh = _shape(str(code).upper())
            counts[(typ, sh)] = counts.get((typ, sh), 0) + 1
    for (typ, sh), n in sorted(counts.items(), key=lambda x: -x[1])[:24]:
        rx = _rx(sh)
        if rx and rx not in seen and (n >= 2 or typ in ("item", "sku")):
            seen.add(rx)
            pats.append({"type": typ, "re": rx, "n": n})
    # 泰国常见快递单号（系统里还没有这种单时也认）
    for typ, rx in (("tracking", r"^TH[0-9OQDILSBZ|]{10,13}[A-Z0-9]?$"), ("tracking", r"^(KEX|KER|SPX|LEX|NJV|BEST)[A-Z0-9]{8,16}$"),
                    ("tracking", r"^[0-9OQDILSBZ|]{12,15}$"), ("order", r"^[0-9]{6}[A-Z0-9]{8}$")):
        if rx not in seen:
            seen.add(rx)
            pats.append({"type": typ, "re": rx})
    for p in pats:                                   # 至少要有 2 个真的数字（「HELLO」「OLD」这种普通的字不算）
        p["re"] = "^(?=(?:[^0-9]*[0-9]){2})" + p["re"][1:]
    return {"v": 1, "patterns": pats[:40], "min_len": 4, "max_len": 40, "confirm_frames": 2, "dedup_ms": 2000,
            "hint": "uppercase, trim; test the text as is and with spaces removed; send matching text as window.onNativeScan(text, 'text')"}
