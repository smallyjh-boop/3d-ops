"""候选池：扩展在模型网站列表页读到的卡片（标题、图、热度数字），进来就按规则打分，后台再让 AI 按泰国电商判断一批（20 个一起问）。
有了实测打印时长 / 克数（采集后分析文件、OrcaSlicer 切片、ERP 生产记录）就用实测的重算分数，并校准以后的估算。"""
import json
import re
import time
from urllib.parse import urlparse

from core.config import load_config

from . import pool, db, rules, sites


def ai_on(cfg=None):
    from core import ai
    return ai.ready(cfg or load_config(), "curate")


def ai_json(cfg, system, obj):
    from core import ai_copy
    return ai_copy.extract_json(ai_copy.call(ai_copy.tcfg(cfg, "curate"), system, json.dumps(obj, ensure_ascii=False)))


def cost_fn(cfg):
    """ERP 的单件成本（core/pricing：材料、机时、包装、失败率）。"""
    from core import pricing

    def f(grams, hours):
        try:
            return pricing.variant_cost(cfg, grams, hours)["total"]
        except Exception:  # noqa: BLE001  成本设置不全
            return 0.0
    return f


def fee(cfg):
    try:        # v2.53：费率引擎（Lazada 默认店铺的实际费率，没有数据 = 设置里的默认扣点）；固定费用折算成比例用不上，这里只取百分比部分
        from core import feerates
        r = feerates.resolve("lazada", None, None, cfg)
        return r["pct"] + (r["fixed"] / 300.0 if r["fixed"] else 0.0)
    except Exception:  # noqa: BLE001
        return rules.tf(cfg.get("platform_fee_rate"), 0.2)


def calib():
    return db.get("calib") or {"m": 1.0, "g": 1.0, "n": 0}


def compute(cfg, c, ai, real=None):
    pp, ex, cat = rules.parts(c, ai, cfg, real=real, calib=calib(), cost_fn=cost_fn(cfg), fee=fee(cfg))
    return pp, ex, cat, rules.score(pp, cfg)


def ovr(r, sc, ex, cat):
    """用户手动改过的优先（重新打分也不覆盖）：分数、类目、「恢复」过的规则排除。返回 (显示分, 排除原因, 类目, 系统算的原分数)。"""
    auto = sc
    if r is not None:
        if (r["score_ovr"] if r["score_ovr"] is not None else -1) >= 0:
            sc = r["score_ovr"]
        if r["cat_ovr"]:
            cat = r["category"]
        if r["ex_ok"]:
            ex = ""
    return sc, ex, cat, auto


def badge(row, cfg=None):
    """扩展角标 / 页面显示用的一条。"""
    ai = db.jl(row["ai"])
    real = db.jl(row["real"])
    est = ""
    if real.get("minutes") or real.get("grams"):
        est = f"{rules.tf(real.get('minutes')) / 60:.1f}h · {rules.tf(real.get('grams')):.0f}g"
        measured = True
    else:
        measured = False
        if ai.get("est_minutes"):
            est = f"{rules.tf(ai['est_minutes']) / 60:.1f}h"
        if ai.get("est_grams"):
            est += f" · {rules.tf(ai['est_grams']):.0f}g"
    return {"score": row["score"], "parts": db.jl(row["parts"]), "excluded": row["excluded"], "excluded_th": rules.REASON_TH.get(row["excluded"], ""),
            "category": row["category"], "category_th": rules.CATEGORY_TH.get(row["category"], ""), "est": est.strip(" ·"), "measured": measured,
            "single": ai.get("single_color"), "flags": rules.flags(ai), "reason": str(ai.get("reason") or "")[:160], "reason_th": str(ai.get("reason_th") or "")[:200], "keywords": ai.get("thai_keywords") or [],
            "price": f"฿{rules.tf(ai.get('price_low')):.0f}–{rules.tf(ai.get('price_high')):.0f}" if ai.get("price_low") else "",
            "ai": bool(ai), "ai_error": row["ai_error"], "status": row["status"], "product_id": row["product_id"],
            "capture_bad": row["capture_bad"], "capture_bad_th": BAD_TH.get(row["capture_bad"], ""), "refreshing": bool(row["refresh_at"]),
            "score_manual": (row["score_ovr"] if row["score_ovr"] is not None else -1) >= 0,
            "score_auto": row["score_auto"] if (row["score_auto"] is not None and row["score_auto"] >= 0) else row["score"],
            "cat_manual": bool(row["cat_ovr"]), "ex_ok": bool(row["ex_ok"]), "note": row["note"] or "", "tags": _tags(row["tags"]),
            "title_manual": bool(row["title_ovr"]), "title_raw": row["title"]}


def _tags(v):
    t = db.jl(v, [])
    return [str(x) for x in t] if isinstance(t, list) else []


BAD_TH = {"没读到模型标题": "ไม่ได้อ่านชื่อโมเดล", "标题是作者 / 店铺名": "ชื่อเป็นชื่อผู้ออกแบบ / ร้าน", "缩略图是头像 / 标志": "รูปย่อเป็นรูปโปรไฟล์ / โลโก้",
          "缩略图不是模型图片（可能是头像）": "รูปย่อไม่ใช่รูปโมเดล (อาจเป็นรูปโปรไฟล์)", "缩略图太小，像头像": "รูปย่อเล็กเกิน คล้ายรูปโปรไฟล์"}
AVATAR_RX = re.compile(r"avatar|/users?/|/profiles?/|/logos?/|/badges?/|gravatar|/icons?/|[?&/_-](?:s|size|w)=?(?:16|24|32|40|48|56|64|72|80|96)(?:\D|$)", re.I)


def capture_check(url, title, author="", thumb="", thumb_w=0):
    """列表页读卡片的常见错误（读成了作者那一块）：标题是作者名、缩略图是头像 / 店铺标志。返回原因（空 = 看起来正常）。
    这样的候选标「采集可能出错」，不交给 AI 打分（AI 会按设计师名字乱猜），可以「重新读取」详情页改正，或批量删掉。"""
    t, a = (title or "").strip(), (author or "").strip()
    if not t:
        return "没读到模型标题"
    if t.startswith("@") or (a and t.lower() == a.lower()):
        return "标题是作者 / 店铺名"
    if thumb:
        site = sites.site_for_url(url) or {}
        lst = site.get("list") or {}
        if AVATAR_RX.search(thumb) or (lst.get("avatar") and re.search(lst["avatar"], thumb, re.I)):
            return "缩略图是头像 / 标志"
        host = (urlparse(thumb).hostname or "").lower()
        if lst.get("model_image") and host in [h.lower() for h in site.get("image_hosts") or []] and not re.search(lst["model_image"], thumb, re.I):
            return "缩略图不是模型图片（可能是头像）"
    try:
        if thumb_w and 0 < float(thumb_w) < 64:
            return "缩略图太小，像头像"
    except (TypeError, ValueError):
        pass
    return ""


GONE_BADGE = {"score": 0, "parts": {}, "excluded": "已忽略 / 已清理", "excluded_th": "", "category": "", "category_th": "", "est": "", "measured": False,
              "single": None, "flags": [], "reason": "", "reason_th": "", "keywords": [], "price": "", "ai": False, "ai_error": "", "status": "ignored",
              "product_id": "", "capture_bad": "", "capture_bad_th": "", "refreshing": False}


def upsert(items, who="", watch_id=0):
    """扩展交来列表页的卡片：存下来、打分。返回 {原链接: 角标}。
    卡片读错了（标题是作者名、图是头像）：标「采集可能出错」不交给 AI；已经存着正确资料的不会被错的覆盖。"""
    cfg = load_config()
    c = db.conn()
    out = {}
    now = time.time()
    for it in (items or [])[:100]:
        if not isinstance(it, dict):
            continue
        url = sites.canonical(str(it.get("url") or ""))
        k = sites.source_key(url)
        if not k:
            continue
        row = c.execute("SELECT * FROM cur_candidates WHERE skey=?", (k,)).fetchone()
        if not row and pool.is_gone(k):          # v2.53：清理掉 / 忽略后清掉的，只留指纹，不再存
            out[str(it.get("url"))] = GONE_BADGE
            continue
        old_del = None            # v2.54.1：手动删除过的又采到了：回收站里那条的备注 / 标签 / 手动分数等带到新行
        if not row:
            tr = c.execute("SELECT data FROM cur_trash WHERE skey=? AND reason='deleted'", (k,)).fetchone()
            old_del = db.jl(tr["data"]) if tr else None
            old_del = old_del if isinstance(old_del, dict) else None
        metrics = {str(a)[:20]: str(b)[:20] for a, b in (it.get("metrics") or {}).items()} if isinstance(it.get("metrics"), dict) else {}
        if row:
            old = db.jl(row["metrics"])
            old.update({a: b for a, b in metrics.items() if b})
            metrics = old
        title = str(it.get("title") or (row["title"] if row else ""))[:200]
        author = str(it.get("author") or (row["author"] if row else ""))[:100]
        thumb = str(it.get("thumb") or "")[:500]
        thumb = thumb if thumb.startswith("https://") else ""
        bad = capture_check(url, title, author, thumb, it.get("thumb_w") or 0)
        reset_ai = False
        if row and bad and not row["capture_bad"] and row["title"]:
            title, author, thumb, bad = row["title"], row["author"], "", ""        # 已经有正确的，不用错的覆盖
        elif row and row["capture_bad"] and not bad:
            reset_ai = True                                                       # 原来读错了，现在对了：重新让 AI 判断
        ai = {} if reset_ai else (db.jl(row["ai"]) if row else {})
        pp, ex, cat, sc = compute(cfg, {"title": title, "author": author, "metrics": metrics}, ai, db.jl(row["real"]) if row else None)
        sc, ex, cat, sc_auto = ovr(row if row else old_del, sc, ex, cat)
        if not row and (ex or sc < pool.settings()["junk_score"]):
            thumb, author, metrics, pp = "", "", {}, {}              # v2.53：新插入的（已有的不动，免得稍后看的候选被清掉作者 / 数据）规则排除 / 分数很低的只留指纹 + 标题，不存图片和细节
        if row:
            c.execute("UPDATE cur_candidates SET url=?, title=?, thumb=CASE WHEN ?<>'' THEN ? ELSE thumb END, author=?, metrics=?, score=?, parts=?, "
                      "excluded=?, category=?, last_seen=?, watch_id=CASE WHEN watch_id=0 THEN ? ELSE watch_id END, capture_bad=?, score_auto=? WHERE skey=?",
                      (url, title, thumb, thumb, author, json.dumps(metrics, ensure_ascii=False), sc, json.dumps(pp), ex, cat, now, watch_id, bad, sc_auto, k))
            if reset_ai:
                c.execute("UPDATE cur_candidates SET ai='', ai_at=0, ai_error='' WHERE skey=?", (k,))
        else:
            c.execute("INSERT INTO cur_candidates(skey, platform, url, title, thumb, author, metrics, score, parts, excluded, category, seen_by, "
                      "first_seen, last_seen, watch_id, capture_bad, score_auto) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (k, sites.platform(url), url, title, thumb, author, json.dumps(metrics, ensure_ascii=False), sc, json.dumps(pp), ex, cat,
                       who[:60], now, now, watch_id, bad, sc_auto))
            if old_del:
                so = old_del.get("score_ovr")
                c.execute("UPDATE cur_candidates SET note=?, tags=?, title_ovr=?, score_ovr=?, cat_ovr=?, ex_ok=? WHERE skey=?",
                          (str(old_del.get("note") or ""), str(old_del.get("tags") or ""), str(old_del.get("title_ovr") or ""),
                           so if so is not None else None, int(old_del.get("cat_ovr") or 0), int(old_del.get("ex_ok") or 0), k))
            c.execute("DELETE FROM cur_trash WHERE skey=? AND reason='deleted'", (k,))       # v2.54.1：删除过的又采到了 = 重新出现，回收站里旧的不要了
        r2 = c.execute("SELECT * FROM cur_candidates WHERE skey=?", (k,)).fetchone()
        out[str(it.get("url"))] = badge(r2, cfg)
    c.commit()
    from . import pipeline
    pipeline.kick()
    return out


def sanity_sweep():
    """已经存着的候选按同样的规则再查一遍（升级后第一次打开候选池时；标题是别的卡片的作者名也算）。返回新标出的个数。"""
    c = db.conn()
    authors = {str(r[0]).strip().lower() for r in c.execute("SELECT DISTINCT author FROM cur_candidates WHERE author<>''")}
    n = 0
    for r in c.execute("SELECT id, url, title, author, thumb FROM cur_candidates WHERE capture_bad='' AND product_id=''").fetchall():
        why = capture_check(r["url"], r["title"], r["author"], r["thumb"])
        if not why and (r["title"] or "").strip().lower() in authors and (r["title"] or "").strip().lower() != (r["author"] or "").strip().lower():
            why = "标题是作者 / 店铺名"
        if why:
            c.execute("UPDATE cur_candidates SET capture_bad=? WHERE id=?", (why, r["id"]))
            n += 1
    c.commit()
    db.put("sanity_v", 1)
    return n


def refresh_from_detail(skey, data):
    """「重新读取」：扩展从详情页读到的标题、作者、第一张图改正候选（清掉「采集可能出错」，重新让 AI 判断）。"""
    c = db.conn()
    r = c.execute("SELECT * FROM cur_candidates WHERE skey=?", (skey,)).fetchone()
    if not r:
        return False
    title = str(data.get("title") or "").strip()[:200] or r["title"]
    author = str(data.get("author") or "").strip()[:100] or r["author"]
    thumb = next((u for u in data.get("image_urls") or [] if isinstance(u, str) and u.startswith("https://")), "")[:500] or r["thumb"]
    bad = capture_check(r["url"], title, author, thumb)
    if bad == "缩略图是头像 / 标志" or bad.startswith("缩略图"):
        thumb, bad = "", capture_check(r["url"], title, author, "")
    cfg = load_config()
    pp, ex, cat, sc = compute(cfg, {"title": title, "author": author, "metrics": db.jl(r["metrics"])}, {}, db.jl(r["real"]))
    sc, ex, cat, sc_auto = ovr(r, sc, ex, cat)
    c.execute("UPDATE cur_candidates SET title=?, author=?, thumb=?, capture_bad=?, ai='', ai_at=0, ai_error='', score=?, parts=?, excluded=?, category=?, "
              "refresh_at=0, score_auto=? WHERE id=?", (title, author, thumb, bad, sc, json.dumps(pp), ex, cat, sc_auto, r["id"]))
    c.commit()
    from . import pipeline
    pipeline.kick()
    return True


def delete_bad(ids=None):
    """删掉「采集可能出错」的候选（没采用过的），进回收站（7 天内能恢复）。ids 空 = 全部。返回删了几个。"""
    c = db.conn()
    q, a = "SELECT id FROM cur_candidates WHERE capture_bad<>'' AND product_id=''", []
    if ids:
        q += f" AND id IN ({','.join('?' for _ in ids)})"
        a = [pool._ids([i])[0] for i in ids]
    return pool.delete_rows([r[0] for r in c.execute(q, a)])


AI_PROMPT = (
    "你是泰国电商（Shopee、Lazada、TikTok Shop）选品顾问，卖家用 3D 打印机按单生产（FDM，PLA / PETG），想做小件、简单、单色、功能性的长尾产品。"
    "对每个模型（只有原站标题、作者、原站热度数字），判断在泰国卖的潜力，输出 JSON。考虑：泰国买家（公寓租房、不能打孔、摩托车和皮卡车主、养猫、多肉和观叶植物、"
    "Art toy 收藏的周边、手机游戏周边、替换件和适配件这类“非买不可”的东西更好卖）；和便宜注塑大货正面竞争的不好卖；"
    "儿童玩具（要 มอก. 认证）、佛像等宗教造型、武器、接触食物、成人用品、品牌和动漫角色要排除（写进 exclude）。"
    "估算一件的打印时长（分钟）、克数、是否单色、零件数、是否要另配五金件（螺丝、磁铁等），合理售价区间（泰铢），竞争程度。"
    "每项都按常识估，不确定就保守。必须仅输出 JSON：{\"items\":[{\"i\":序号,\"category\":\"车和摩托配件|替换件适配件|收纳整理|宠物|植物园艺|桌面办公|手机电脑配件|厨房卫浴|装饰摆件|玩具手办|其他\","
    "\"demand\":0-100,\"buyer\":\"谁会买（中文，10 字内）\",\"thai_keywords\":[\"泰文搜索词\"],\"est_minutes\":数字,\"est_grams\":数字,\"single_color\":true/false,"
    "\"parts\":数字,\"needs_hardware\":true/false,\"price_low\":数字,\"price_high\":数字,\"competition\":\"low|medium|high\",\"listing\":0-100,"
    "\"exclude\":\"排除原因或空字符串\",\"reason\":\"一句中文理由（30 字内）\",\"reason_th\":\"同一句理由的泰文\"}]}")
AI_KEYS = ("category", "demand", "buyer", "thai_keywords", "est_minutes", "est_grams", "single_color", "parts", "needs_hardware",
           "price_low", "price_high", "competition", "listing", "exclude", "reason", "reason_th")


def ai_batch(cfg=None, limit=20):
    """后台：还没 AI 判断的候选，一次 limit 个一起问。返回处理了几个（0 = 没有要做的 / 没设 AI）。"""
    cfg = cfg or load_config()
    if not ai_on(cfg):
        return 0
    c = db.conn()
    rows = c.execute("SELECT * FROM cur_candidates WHERE ai_at=0 AND ai_error='' AND capture_bad='' AND status<>'ignored' ORDER BY last_seen DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        return 0
    items = [{"i": n, "title": r["title"], "author": r["author"], "platform": r["platform"], "metrics": db.jl(r["metrics"])} for n, r in enumerate(rows)]
    try:
        out = ai_json(cfg, AI_PROMPT, {"items": items})
        got = {int(rules.tf(x.get("i"), -1)): x for x in out.get("items") or [] if isinstance(x, dict)}
    except Exception as e:  # noqa: BLE001
        for r in rows:
            c.execute("UPDATE cur_candidates SET ai_error=? WHERE id=?", (str(e)[:200], r["id"]))
        c.commit()
        return len(rows)
    for n, r in enumerate(rows):
        a = got.get(n)
        if not a:
            c.execute("UPDATE cur_candidates SET ai_error='AI 没有返回' WHERE id=?", (r["id"],))
            continue
        a = {k: a.get(k) for k in AI_KEYS}
        pp, ex, cat, sc = compute(cfg, {"title": r["title"], "author": r["author"], "metrics": db.jl(r["metrics"])}, a, db.jl(r["real"]))
        sc, ex, cat, sc_auto = ovr(r, sc, ex, cat)
        c.execute("UPDATE cur_candidates SET ai=?, ai_at=?, score=?, parts=?, excluded=?, category=?, score_auto=? WHERE id=?",
                  (json.dumps(a, ensure_ascii=False), time.time(), sc, json.dumps(pp), ex, cat, sc_auto, r["id"]))
    c.commit()
    return len(rows)


def rescore_all(cfg=None):
    """改了权重 / 上限 / 校准以后全部重算（不再问 AI）。"""
    cfg = cfg or load_config()
    c = db.conn()
    for r in c.execute("SELECT * FROM cur_candidates").fetchall():
        pp, ex, cat, sc = compute(cfg, {"title": r["title"], "author": r["author"], "metrics": db.jl(r["metrics"])}, db.jl(r["ai"]), db.jl(r["real"]))
        sc, ex, cat, sc_auto = ovr(r, sc, ex, cat)
        c.execute("UPDATE cur_candidates SET score=?, parts=?, excluded=?, category=?, score_auto=? WHERE id=?", (sc, json.dumps(pp), ex, cat, sc_auto, r["id"]))
    c.commit()


# 候选池的三个页签（回收站另算）：采用了的不在池子里（在采集箱 / 产品库），只在「已采用」里；和 pool._key 的分法一致
INPOOL = "product_id='' AND status<>'adopted'"
TAB_SQL = {"pending": "product_id='' AND status<>'adopted' AND status<>'ignored' AND (status='later' OR excluded='')",
           "done": "product_id='' AND status<>'adopted' AND (status='ignored' OR (status<>'later' AND excluded<>''))",
           "adopted": "(product_id<>'' OR status='adopted')",
           "all": INPOOL}                                  # 池子里的全部（不含已采用）：「看这个巡逻的全部 / 采集可能出错的」用


def listing(args, owner=True):
    """候选池列表 + 数字卡片。args：tab(pending 待处理（默认）/ done 已处理 / adopted 已采用 / trash 回收站), min, platform, cat, new(今日新品), watch, q, bad, gk(自动分组)。
    老参数 status / ex 还认（没传 tab 时按 v2.53 的老规矩）。"""
    c = db.conn()
    if not db.get("sanity_v"):
        sanity_sweep()
    where, a = ["score>=?"], [rules.tf(args.get("min"), 0)]
    if args.get("platform"):
        where.append("platform=?"); a.append(args["platform"])
    if args.get("cat"):
        where.append("category=?"); a.append(args["cat"])
    if str(args.get("new")) == "1":
        where.append("new_at>=?"); a.append(db.day_start())
    if args.get("watch"):
        where.append("watch_id=?"); a.append(int(rules.tf(args["watch"])))
    if str(args.get("bad")) == "1":
        where.append("capture_bad<>''")
    if args.get("q"):
        where.append("(title LIKE ? OR title_ovr LIKE ? OR author LIKE ? OR note LIKE ? OR tags LIKE ?)"); a += [f"%{args['q']}%"] * 5
    gk = [x for x in str(args.get("gk") or "").split(",") if x]
    alert = rules.tf(load_config().get("cur_alert_score"), 70)
    idx, gn = pool.group_index(alert)
    if gk:                                        # v2.53 自动分组：几个并起来
        ok_ids = [i for i, g in idx.items() if all(x in g for x in gk)]
        where.append(f"id IN ({','.join(str(int(i)) for i in ok_ids) or '0'})")
    tab = args.get("tab") if args.get("tab") in ("pending", "done", "adopted", "trash", "all") else ""
    by_group = any(x.startswith(("pg:", "top:")) for x in gk)          # 选了进度 / 顶部分组：状态由分组定
    legacy = not tab and not gk and ("status" in args or "ex" in args)
    if legacy:                                    # v2.53 老参数
        if str(args.get("ex")) != "1":
            where.append("excluded=''")
        st = args.get("status") or "open"
        if st == "open":
            where.append("status=''")
        elif st != "all":
            where.append("status=?"); a.append(st)
    elif not by_group:
        tab = tab or "pending"
        if tab != "trash":
            where.append(TAB_SQL[tab])
    rows = c.execute(f"SELECT * FROM cur_candidates WHERE {' AND '.join(where)} ORDER BY score DESC, last_seen DESC LIMIT 300", a).fetchall() if tab != "trash" else []
    cfg = load_config()
    from . import demand
    dem = demand.matcher()
    out = []
    for r in rows:
        b = badge(r, cfg)
        b.update(id=r["id"], url=r["url"], title=r["title_ovr"] or r["title"], thumb=r["thumb"], author=r["author"], platform=r["platform"],
                 platform_name=sites.name_of(r["platform"]), metrics=db.jl(r["metrics"]), new=r["new_at"] >= db.day_start(),
                 watch_id=r["watch_id"], last_seen=r["last_seen"], market=dem(r["title"], (db.jl(r["ai"]).get("thai_keywords") or []), r["category"]))
        out.append(b)
    t0 = db.day_start()
    k = {"total": c.execute(f"SELECT COUNT(*) FROM cur_candidates WHERE {INPOOL}").fetchone()[0],
         "good": c.execute(f"SELECT COUNT(*) FROM cur_candidates WHERE {INPOOL} AND excluded='' AND score>=? AND status=''",
                           (rules.tf(cfg.get("cur_alert_score"), 70),)).fetchone()[0],
         "new_today": c.execute(f"SELECT COUNT(*) FROM cur_candidates WHERE {INPOOL} AND new_at>=? AND excluded=''", (t0,)).fetchone()[0],
         "excluded": c.execute(f"SELECT COUNT(*) FROM cur_candidates WHERE {INPOOL} AND excluded<>''").fetchone()[0],
         "bad": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE capture_bad<>'' AND product_id=''").fetchone()[0],
         "wait_ai": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE ai_at=0 AND ai_error='' AND capture_bad=''").fetchone()[0] if ai_on(cfg) else 0}
    hist = [0] * 10
    for r in c.execute(f"SELECT score FROM cur_candidates WHERE {INPOOL} AND excluded=''"):
        hist[min(9, int(r[0] // 10))] += 1
    reasons = [{"reason": r[0], "reason_th": rules.REASON_TH.get(r[0], ""), "n": r[1]}
               for r in c.execute("SELECT excluded, COUNT(*) FROM cur_candidates WHERE excluded<>'' GROUP BY excluded ORDER BY 2 DESC LIMIT 6")]
    cats = [{"name": r[0], "th": rules.CATEGORY_TH.get(r[0], r[0])} for r in c.execute(f"SELECT DISTINCT category FROM cur_candidates WHERE {INPOOL} AND category<>'' ORDER BY category")]
    have = {x["name"] for x in cats}
    all_cats = cats + [{"name": k, "th": v} for k, v in rules.CATEGORY_TH.items() if k not in have]      # 编辑类目时可选的（用过的 + AI 的固定分类）
    res = {"rows": out, "kpi": k, "radar": demand.has_radar(), "hist": hist, "reasons": reasons, "cats": cats, "all_cats": all_cats, "ai": ai_on(cfg), "calib": calib(),
           "alert_score": rules.tf(cfg.get("cur_alert_score"), 70)}
    res["groups"] = pool.summary(pool.tab_counts_of(idx, tab) if tab in ("pending", "done") and not by_group else gn)
    res["groups"]["n"] = gn                      # n = 全部（v2.53 的老样子）；tn = 当前页签里各分组的个数（页面上画这个）
    res["groups"]["total"] = gn.get("all", 0)
    res["groups"]["tn"] = pool.tab_counts_of(idx, tab) if tab in ("pending", "done", "all") and not by_group else gn
    res["pool"] = pool.kpis()
    res["tab"] = tab if not (legacy or by_group) else ""
    res["tabs"] = {"pending": gn.get("tab:pending", 0), "done": gn.get("tab:done", 0), "adopted": gn.get("tab:adopted", 0),
                   "trash": c.execute("SELECT COUNT(*) FROM cur_trash").fetchone()[0]}
    if tab == "trash" and not (legacy or by_group):
        res["trash"] = pool.trash_list()
    if not owner:
        for r in res["rows"]:
            r["parts"].pop("profit", None)
            r.pop("price", None)
    return res


def set_status(ids, status):
    """"" 回到待处理 · later 稍后看 · seen 标为已看 · ignored 忽略（不再出现）。已采用的不动。"""
    if status not in ("", "ignored", "later", "seen"):
        raise ValueError("状态不对")
    ids = pool._ids(ids)
    if status == "seen":
        return pool.set_seen(ids)
    c = db.conn()
    c.executemany("UPDATE cur_candidates SET status=?, seen_at=CASE WHEN ?<>'' THEN ? ELSE seen_at END WHERE id=? AND status<>'adopted' AND product_id=''",
                  [(status, status, time.time(), i) for i in ids])
    c.commit()


def _clean_tags(v):
    if isinstance(v, str):
        v = re.split(r"[,，;；\n]+", v)
    if not isinstance(v, (list, tuple)):
        raise ValueError("标签格式不对")
    out = []
    for t in v:
        t = str(t).strip()[:20]
        if t and t not in out:
            out.append(t)
    return out[:10]


def edit_row(cid, d):
    """编辑一条：category 类目 · score 手动分数（0–100，留空 = 回到系统算的）· note 备注 · tags 标签 · title 标题（留空 = 用原标题）。
    手动改的类目 / 分数重新打分、AI 判断后也不会被覆盖；原来系统算的分数一直留着（score_auto），页面上同时显示。"""
    c = db.conn()
    r = c.execute("SELECT * FROM cur_candidates WHERE id=?", (pool._ids([cid])[0],)).fetchone()
    if not r:
        raise ValueError("没有这个候选")
    d = d or {}
    sets, args, redo = [], [], False
    if "category" in d:
        cat = str(d["category"] or "").strip()[:40]
        if cat:
            sets += ["category=?", "cat_ovr=1"]; args.append(cat)
        else:
            sets.append("cat_ovr=0"); redo = True
    if "score" in d:
        if d["score"] is None or (isinstance(d["score"], str) and not d["score"].strip()):
            sets.append("score_ovr=-1"); redo = True
        else:
            f = pool.fnum(d["score"], 0, 100)
            sets += ["score_ovr=?", "score=?"]; args += [f, f]
            if (r["score_auto"] if r["score_auto"] is not None else -1) < 0 and (r["score_ovr"] if r["score_ovr"] is not None else -1) < 0:
                sets.append("score_auto=?"); args.append(r["score"])          # 老数据没存原分数：改之前的分数就是系统算的
    if "note" in d:
        sets.append("note=?"); args.append(str(d["note"] or "").strip()[:500])
    if "tags" in d:
        sets.append("tags=?"); args.append(json.dumps(_clean_tags(d["tags"] or []), ensure_ascii=False))
    if "title" in d:
        sets.append("title_ovr=?"); args.append(str(d["title"] or "").strip()[:200])
    if sets:
        c.execute(f"UPDATE cur_candidates SET {', '.join(sets)} WHERE id=?", [*args, r["id"]])
        c.commit()
    if redo:                                       # 去掉手动值：按系统算的重新打分
        r = c.execute("SELECT * FROM cur_candidates WHERE id=?", (r["id"],)).fetchone()
        pp, ex, cat, sc = compute(load_config(), {"title": r["title"], "author": r["author"], "metrics": db.jl(r["metrics"])}, db.jl(r["ai"]), db.jl(r["real"]))
        sc, ex, cat, sc_auto = ovr(r, sc, ex, cat)
        c.execute("UPDATE cur_candidates SET score=?, parts=?, excluded=?, category=?, score_auto=? WHERE id=?", (sc, json.dumps(pp), ex, cat, sc_auto, r["id"]))
        c.commit()
    return {"id": r["id"]}
