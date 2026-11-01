"""v2.55 打印机编码规则（像货位编码一样用「积木」拼）。

规则 = 一串积木 + 分隔符：
  fixed  固定前缀（例如 PR）          group  分组（A 区 → A；可在「分组简称」里指定）
  loc    位置里的 机架-层-位（A-03-2 → A-03-2）      model  机型简称（fleet.prefix_for：P1S / K1C …）
  seq    顺序号，位数 2 / 3 / 4，范围：per model（同机型）/ group（同分组）/ global（全部）
分隔符：- 或 _ 或不要。例：A-P1S-001（分组 + 机型 + 顺序号）。

设置存在 config["printer_code_rules"] = {"rules": {规则 id: {name, blocks, sep}}, "default": 规则 id,
                                          "groups": {分组: 规则 id}, "group_codes": {分组: 简称}}。
打印机身份是稳定 id，编码只是显示用的名字：改编码不会动任务 / 打印记录（按 id 对）；还存着编码的地方
（料卷装在哪台、出入库记录里的打印机、仓库生产区货位）由 rename_refs 一起改。
"""
import re
import time

from . import db, fleet

SEPS = ("-", "_", "")
BLOCK_TYPES = ("fixed", "group", "loc", "model", "seq")
SCOPES = ("model", "group", "global")
WIDTHS = (2, 3, 4)
MAX_BLOCKS = 6
MAX_RULES = 30
STD = "std"
BUILTIN = {"name": "标准（机型-顺序号）", "blocks": [{"t": "model"}, {"t": "seq", "width": 3, "scope": "model"}], "sep": "-"}


def _alnum(s, n=0):
    s = re.sub(r"[^A-Za-z0-9]", "", str(s or "")).upper()
    return s[:n] if n else s


def clean_rule(r):
    """检查并整理一条规则。返回 (规则, 错误[(中文, 泰文)])。"""
    errs = []
    r = r if isinstance(r, dict) else {}
    name = str(r.get("name") or "").strip()[:30]
    sep = r.get("sep", "-")
    sep = "" if sep in (None, "none", "空") else str(sep)
    if sep not in SEPS:
        errs.append(("分隔符只能是 - 或 _ 或不要", "ตัวคั่นใช้ได้เฉพาะ - หรือ _ หรือไม่ใช้"))
        sep = "-"
    blocks = []
    raw = r.get("blocks")
    if not isinstance(raw, list) or not raw:
        errs.append(("规则至少要有一个积木", "กฎต้องมีอย่างน้อยหนึ่งบล็อก"))
        raw = []
    if len(raw) > MAX_BLOCKS:
        errs.append((f"积木最多 {MAX_BLOCKS} 个", f"บล็อกได้ไม่เกิน {MAX_BLOCKS} อัน"))
    nseq = 0
    for b in raw[:MAX_BLOCKS]:
        t = (b or {}).get("t")
        if t not in BLOCK_TYPES:
            errs.append((f"不认得的积木「{t}」", f"ไม่รู้จักบล็อก «{t}»"))
            continue
        o = {"t": t}
        if t == "fixed":
            v = _alnum(b.get("v"), 8)
            if not v:
                errs.append(("固定前缀要填（英文或数字，最多 8 位）", "ต้องกรอกคำนำหน้าคงที่ (อังกฤษหรือตัวเลข ไม่เกิน 8 ตัว)"))
            o["v"] = v
        elif t == "seq":
            nseq += 1
            try:
                w = int(b.get("width") or 3)
            except (TypeError, ValueError):
                w = 0
            if w not in WIDTHS:
                errs.append(("顺序号位数只能是 2、3、4", "จำนวนหลักของลำดับใช้ได้เฉพาะ 2, 3, 4"))
                w = 3
            sc = b.get("scope") or "model"
            if sc not in SCOPES:
                errs.append(("顺序号范围只能是 同机型 / 同分组 / 全部", "ขอบเขตลำดับใช้ได้เฉพาะ ตามรุ่น / ตามกลุ่ม / ทั้งหมด"))
                sc = "model"
            o.update(width=w, scope=sc)
        blocks.append(o)
    if nseq > 1:
        errs.append(("顺序号积木只能有一个", "บล็อกลำดับมีได้เพียงหนึ่งอัน"))
    return {"name": name, "blocks": blocks, "sep": sep}, errs


def get_rules(cfg):
    """整理过的规则设置（没设置过 = 内置的「机型-顺序号」，和以前自动编码一样：P1S-001）。"""
    raw = (cfg or {}).get("printer_code_rules") or {}
    rules = {}
    for rid, r in (raw.get("rules") or {}).items():
        rr, errs = clean_rule(r)
        if not errs:
            rules[str(rid)] = rr
    if not rules:
        rules[STD] = dict(BUILTIN, blocks=[dict(b) for b in BUILTIN["blocks"]])
    default = raw.get("default") if raw.get("default") in rules else next(iter(rules))
    groups = {g: rid for g, rid in (raw.get("groups") or {}).items() if rid in rules}
    gcodes = {g: _alnum(c, 6) for g, c in (raw.get("group_codes") or {}).items() if _alnum(c, 6)}
    return {"rules": rules, "default": default, "groups": groups, "group_codes": gcodes}


def rule_id_for(group, rs):
    return rs["groups"].get(group or "") or rs["default"]


def rule_for(p, cfg, override=None):
    rs = get_rules(cfg)
    rid = override if override in rs["rules"] else rule_id_for(p.get("group"), rs)
    return rid, rs["rules"][rid], rs


# ---------------- 拼编码 ----------------
def loc_token(loc, sep):
    parts = re.findall(r"[A-Za-z]+|\d+", str(loc or ""))
    return sep.join(x.upper() for x in parts)


def token(t, p, rule, rs):
    if t == "fixed":
        return ""
    if t == "model":
        return fleet.prefix_for(p.get("name"))
    if t == "group":
        g = str(p.get("group") or "").strip()
        return rs["group_codes"].get(g) or _alnum(g, 4)
    if t == "loc":
        return loc_token(p.get("location"), rule["sep"])
    return ""


def tokens(p, rule, rs):
    """按积木顺序的片段：[(类型, 文本)]；顺序号位置用 ("seq", None)。空片段（比如没填位置）跳过。"""
    out = []
    for b in rule["blocks"]:
        if b["t"] == "seq":
            out.append(("seq", None))
        elif b["t"] == "fixed":
            if b.get("v"):
                out.append(("fixed", b["v"]))
        else:
            tk = token(b["t"], p, rule, rs)
            if tk:
                out.append((b["t"], tk))
    return out


def render(toks, rule, seq):
    width = next((b.get("width", 3) for b in rule["blocks"] if b["t"] == "seq"), 3)
    return rule["sep"].join(f"{seq:0{width}d}" if tx is None else tx for _t, tx in toks)


def seq_of(code, p, rule, rs):
    """这个编码是不是按这条规则、用这台自己的分组 / 位置 / 机型拼的？是 → 返回它的顺序号（没有顺序号积木的规则返回 0），否则 None。"""
    toks = tokens(p, rule, rs)
    sep = re.escape(rule["sep"])
    pat = sep.join(r"(\d+)" if tx is None else re.escape(tx) for _t, tx in toks)
    m = re.fullmatch(pat, str(code or "").upper()) if pat else None
    if not m:
        return None
    return int(m.group(1)) if m.groups() else 0


def _in_scope(q, p, scope):
    if scope == "global":
        return True
    if scope == "group":
        return (q.get("group") or "") == (p.get("group") or "")
    return fleet.prefix_for(q.get("name")) == fleet.prefix_for(p.get("name"))


def check_code(code, printers, exclude_id=None):
    """手填编码的检查：返回错误 (中文, 泰文) 或 None。不分大小写查重。"""
    code = str(code or "").strip().upper()
    if not code:
        return ("编码不能为空", "รหัสต้องไม่ว่าง")
    if not fleet.CODE_RE.match(code):
        return (f"机器编码「{code}」只能用英文、数字和 - _，最多 16 位", f"รหัสเครื่อง «{code}» ใช้ได้เฉพาะอังกฤษ ตัวเลข - _ ไม่เกิน 16 ตัว")
    for q in printers:
        if q.get("id") != exclude_id and str(q.get("code") or "").upper() == code:
            return (f"机器编码「{code}」已经有了", f"รหัสเครื่อง «{code}» มีอยู่แล้ว")
    if code in fleet.retired_codes(printers, exclude_id):
        return (f"机器编码「{code}」是别的打印机以前用过的编码（旧标签还贴着），不能再用", f"รหัส «{code}» เคยเป็นของเครื่องอื่น (ป้ายเก่ายังติดอยู่) ใช้ซ้ำไม่ได้")
    return None


def code_for(p, pool, cfg, rule_override=None):
    """给 p 按规则拼一个编码，避开 pool（已有的打印机，不含 p 自己）里用掉的编码和顺序号。返回 (编码, 问题)；
    问题：None / 'dup'（规则里没有顺序号，拼出来重复）/ 'long'（超过 16 位）/ 'empty'。"""
    rid, rule, rs = rule_for(p, cfg, rule_override)
    toks = tokens(p, rule, rs)
    used = {str(q.get("code") or "").upper() for q in pool} | fleet.retired_codes(pool, p.get("id"))
    seqb = next((b for b in rule["blocks"] if b["t"] == "seq"), None)
    if not toks:
        return "", "empty"
    if seqb is None:
        code = render(toks, rule, 0)
        return code, ("dup" if code in used else "long" if len(code) > 16 else None)
    taken = set()
    for q in pool:
        if not _in_scope(q, p, seqb["scope"]):
            continue
        _rid, qr, qrs = rule_for(q, cfg, rule_override)
        s = seq_of(q.get("code"), q, qr, qrs)
        if s:
            taken.add(s)
    k = 1
    while k in taken or render(toks, rule, k) in used:
        k += 1
    code = render(toks, rule, k)
    return code, ("long" if len(code) > 16 else None)


PROBLEM = {"dup": ("规则里没有顺序号，拼出来的编码重复了", "กฎไม่มีลำดับ รหัสที่ได้ซ้ำกัน"),
           "long": ("拼出来的编码超过 16 位", "รหัสที่ได้ยาวเกิน 16 ตัว"),
           "empty": ("规则拼不出编码（积木都是空的）", "กฎสร้างรหัสไม่ได้ (บล็อกว่างทั้งหมด)")}


def generate(printers, specs, cfg, rule_override=None):
    """一批新打印机（specs：{name, group, location}）按规则依次编码，后面的会避开前面刚编的。返回 [(编码, 问题)]。"""
    pool = list(printers)
    out = []
    for s in specs:
        code, prob = code_for(s, pool, cfg, rule_override)
        pool.append(dict(s, code=code))
        out.append((code, prob))
    return out


def auto_codes(printers, specs, cfg):
    """添加 / 发现 / 导入用：失败（规则拼不出）时抛 ValueError，带中泰文。"""
    res = generate(printers, specs, cfg)
    for code, prob in res:
        if prob:
            raise ValueError(PROBLEM[prob])
    return [c for c, _p in res]


# ---------------- 预览（规则编辑器） ----------------
SAMPLES = [("Bambu Lab P1S", "A 区", "A-03-2"), ("Bambu Lab P1S", "A 区", "A-03-3"), ("Creality K1C", "B 区", "B-01-1"), ("Bambu Lab P1S", "B 区", "B-01-2")]


def preview(rule, cfg, group_codes=None):
    """规则草稿的例子（用一个空的机群拼，所以不受现有编码影响）。返回 (规则, 错误, 例子[{name, group, location, code}])。"""
    rr, errs = clean_rule(rule)
    if errs:
        return rr, errs, []
    c2 = {"printer_code_rules": {"rules": {"x": rr}, "default": "x", "group_codes": group_codes or (get_rules(cfg)["group_codes"])}}
    specs = [{"name": n, "group": g, "location": loc} for n, g, loc in SAMPLES]
    res = generate([], specs, c2)
    ex = [dict(s, code=c, problem=PROBLEM[pr] if pr else None) for s, (c, pr) in zip(specs, res)]
    return rr, [], ex


# ---------------- 批量重新编号 ----------------
def _natkey(s):
    return [int(x) if x.isdigit() else x for x in re.findall(r"\d+|\D+", str(s or "").upper())]


ORDERS = ("location", "code", "list")


def plan_renumber(printers, sel_ids, cfg, rule_override=None, order="location"):
    """选中的打印机按规则重新编号（预览，不改东西）。返回行 [{id, old, new, status, problem, group, location, name}]：
    status：same（没变）/ change / conflict（和没选中的重复 / 选中的里重复 / 不合法）。"""
    sel = [p for p in printers if p.get("id") in sel_ids]
    rest = [p for p in printers if p.get("id") not in sel_ids]
    if order == "code":
        sel.sort(key=lambda p: _natkey(p.get("code")))
    elif order == "location":
        sel.sort(key=lambda p: (_natkey(p.get("group")), _natkey(p.get("location")), _natkey(p.get("code"))))
    pool = list(rest)
    rows = []
    for p in sel:
        q = dict(p, code="")
        code, prob = code_for(q, pool, cfg, rule_override)
        pool.append(dict(p, code=code))
        row = {"id": p.get("id"), "old": p.get("code") or "", "new": code, "name": p.get("name") or "", "group": p.get("group") or "",
               "location": p.get("location") or "", "problem": None, "status": "change"}
        if prob:
            row["problem"] = PROBLEM[prob]
            row["status"] = "conflict"
        elif code == (p.get("code") or ""):
            row["status"] = "same"
        rows.append(row)
    # 选中的里重复 / 和没选中的重复
    seen = {}
    for r in rows:
        if r["new"]:
            seen.setdefault(r["new"].upper(), []).append(r)
    rest_codes = {str(p.get("code") or "").upper() for p in rest}
    for k, rs_ in seen.items():
        if len(rs_) > 1 or k in rest_codes:
            for r in rs_:
                r["status"] = "conflict"
                r["problem"] = ("编码重复了", "รหัสซ้ำกัน")
    return rows


# ---------------- 改完编码，其他地方存的编码一起改 ----------------
def _has(c, t):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None


def rename_codes(pairs):
    """pairs = [(旧编码, 新编码)]。先全部挪到临时名字再改成新的，所以两台互换编码（A↔B）也不会串。
    改的地方：料卷装在哪台（spools.printer）、出入库记录 / 单据里的打印机（inv_moves.printer / inv_docs.printer）。
    任务 / 打印记录 / 保养 / 失败按序号存、生产单按稳定 id 存，不用改；仓库生产区货位由仓库模块按稳定 id 同步。"""
    pairs = [(o, n) for o, n in pairs if o and n and o != n]
    if not pairs:
        return 0
    c = db.conn()
    now = time.time()
    n = 0
    for t, extra in (("spools", ", updated_at=%f" % now), ("inv_moves", ""), ("inv_docs", "")):
        if not _has(c, t):
            continue
        for i, (o, _n) in enumerate(pairs):
            c.execute(f"UPDATE {t} SET printer=?{extra} WHERE printer=?", (f"~~tmp{i}~~", o))
        for i, (_o, nw) in enumerate(pairs):
            n += c.execute(f"UPDATE {t} SET printer=? WHERE printer=?", (nw, f"~~tmp{i}~~")).rowcount
    c.commit()
    return n


def migrate_po_refs():
    """生产单里还存着旧编码 / 序号的，先换成稳定 id（改编码之前做，不然会找不到）。"""
    try:
        from . import po
        c = db.conn()
        if _has(c, "production_orders"):
            po._migrate_refs(c, fleet_printers())
    except Exception:  # noqa: BLE001
        pass


def fleet_printers():
    from .config import load_config
    return load_config().get("printers") or []


def remember_old(p, old):
    """旧编码记下来（最多 5 个）：以前印的二维码标签扫了还能找到这台。"""
    if old and old != p.get("code"):
        hist = [x for x in (p.get("old_codes") or []) if x != old and x != p.get("code")]
        p["old_codes"] = ([old] + hist)[:5]


def note_code_changes(old, new):
    """v2.55.0 每一处改编码（单台修改 / 设置页保存 / 批量重新编号）都走这里：新旧两个列表按稳定 id 对，
    改了编码的 → 旧编码记进 old_codes（以前印的标签还能找到）；旧编码现在已经是别的打印机的当前编码（互换 / 复用）→
    不能再当旧标签认（会悄悄打开错的机器），改记进 stale_codes，扫到时提示「这个编码已换给别的打印机，请重新打印标签」。
    原地修改 new。返回 {changed: [id], relabel: [{id, code, old, now_of}]}：relabel = 旧标签会指到别的机器、必须重新打印的。"""
    oid = {p.get("id"): p for p in old if p.get("id")}
    changed = []
    for p in new:
        o = oid.get(p.get("id"))
        if o and (o.get("code") or "") != (p.get("code") or ""):
            remember_old(p, o.get("code"))
            changed.append(p.get("id"))
    cur = {}
    for p in new:
        if p.get("code"):
            cur.setdefault(str(p["code"]).upper(), p)
    relabel = []
    for p in new:
        mine = str(p.get("code") or "").upper()
        keep, stale = [], [x for x in (p.get("stale_codes") or []) if str(x).upper() != mine]
        for x in p.get("old_codes") or []:
            u = str(x).upper()
            if u == mine:
                continue
            owner = cur.get(u)
            if owner is not None and owner is not p:
                if x not in stale:
                    stale.append(x)
                if p.get("id") in changed:
                    relabel.append({"id": p.get("id"), "code": p.get("code"), "old": x, "now_of": owner.get("code")})
            else:
                keep.append(x)
        if keep or p.get("old_codes"):
            p["old_codes"] = keep
        if stale or p.get("stale_codes"):
            p["stale_codes"] = stale[:10]
    return {"changed": changed, "relabel": relabel}


# ---------------- 改位置 / 分组时：编码里带着旧的 → 建议重新编号 ----------------
def embeds(p_old, cfg, need=("group", "loc")):
    """这台打印机现在的编码是不是按规则、用旧的分组 / 位置拼出来的，并且规则里有 need 里的积木（分组 / 位置）？"""
    rid, rule, rs = rule_for(p_old, cfg)
    if not any(b["t"] in need for b in rule["blocks"]):
        return False
    return seq_of(p_old.get("code"), p_old, rule, rs) is not None


def suggest_after_move(olds, news, cfg):
    """olds / news：改动前后的打印机（同一批，按 id 对）。返回应该提示「要按新位置重新编号吗？」的打印机 id 列表。"""
    out = []
    nid = {p.get("id"): p for p in news}
    for o in olds:
        n = nid.get(o.get("id"))
        if not n or ((o.get("group") or "") == (n.get("group") or "") and (o.get("location") or "") == (n.get("location") or "")):
            continue
        need = tuple(k for k, f in (("group", "group"), ("loc", "location")) if (o.get(f) or "") != (n.get(f) or ""))
        if embeds(o, cfg, need):
            out.append(o.get("id"))
    return out
