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
    return rules.tf(cfg.get("platform_fee_rate"), 0.2)


def calib():
    return db.get("calib") or {"m": 1.0, "g": 1.0, "n": 0}


def compute(cfg, c, ai, real=None):
    pp, ex, cat = rules.parts(c, ai, cfg, real=real, calib=calib(), cost_fn=cost_fn(cfg), fee=fee(cfg))
    return pp, ex, cat, rules.score(pp, cfg)


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
            "capture_bad": row["capture_bad"], "capture_bad_th": BAD_TH.get(row["capture_bad"], ""), "refreshing": bool(row["refresh_at"])}


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
        if (ex or sc < pool.settings()["junk_score"]) and not (row and (row["product_id"] or row["status"] == "adopted")):
            thumb, author, metrics, pp = "", "", {}, {}              # v2.53：规则排除 / 分数很低的只留指纹 + 标题，不存图片和细节
        if row:
            c.execute("UPDATE cur_candidates SET url=?, title=?, thumb=CASE WHEN ?<>'' THEN ? ELSE thumb END, author=?, metrics=?, score=?, parts=?, "
                      "excluded=?, category=?, last_seen=?, watch_id=CASE WHEN watch_id=0 THEN ? ELSE watch_id END, capture_bad=? WHERE skey=?",
                      (url, title, thumb, thumb, author, json.dumps(metrics, ensure_ascii=False), sc, json.dumps(pp), ex, cat, now, watch_id, bad, k))
            if reset_ai:
                c.execute("UPDATE cur_candidates SET ai='', ai_at=0, ai_error='' WHERE skey=?", (k,))
        else:
            c.execute("INSERT INTO cur_candidates(skey, platform, url, title, thumb, author, metrics, score, parts, excluded, category, seen_by, "
                      "first_seen, last_seen, watch_id, capture_bad) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (k, sites.platform(url), url, title, thumb, author, json.dumps(metrics, ensure_ascii=False), sc, json.dumps(pp), ex, cat,
                       who[:60], now, now, watch_id, bad))
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
    c.execute("UPDATE cur_candidates SET title=?, author=?, thumb=?, capture_bad=?, ai='', ai_at=0, ai_error='', score=?, parts=?, excluded=?, category=?, "
              "refresh_at=0 WHERE id=?", (title, author, thumb, bad, sc, json.dumps(pp), ex, cat, r["id"]))
    c.commit()
    from . import pipeline
    pipeline.kick()
    return True


def delete_bad(ids=None):
    """删掉「采集可能出错」的候选（没采用过的）。ids 空 = 全部。返回删了几个。"""
    c = db.conn()
    q, a = "DELETE FROM cur_candidates WHERE capture_bad<>'' AND product_id=''", []
    if ids:
        q += f" AND id IN ({','.join('?' for _ in ids)})"
        a = [int(i) for i in ids]
    n = c.execute(q, a).rowcount
    c.commit()
    return n


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
        c.execute("UPDATE cur_candidates SET ai=?, ai_at=?, score=?, parts=?, excluded=?, category=? WHERE id=?",
                  (json.dumps(a, ensure_ascii=False), time.time(), sc, json.dumps(pp), ex, cat, r["id"]))
    c.commit()
    return len(rows)


def rescore_all(cfg=None):
    """改了权重 / 上限 / 校准以后全部重算（不再问 AI）。"""
    cfg = cfg or load_config()
    c = db.conn()
    for r in c.execute("SELECT * FROM cur_candidates").fetchall():
        pp, ex, cat, sc = compute(cfg, {"title": r["title"], "author": r["author"], "metrics": db.jl(r["metrics"])}, db.jl(r["ai"]), db.jl(r["real"]))
        c.execute("UPDATE cur_candidates SET score=?, parts=?, excluded=?, category=? WHERE id=?", (sc, json.dumps(pp), ex, cat, r["id"]))
    c.commit()


def listing(args, owner=True):
    """候选池列表 + 数字卡片。args：min, platform, cat, ex(显示排除的), new(今日新品), watch, q, status"""
    c = db.conn()
    if not db.get("sanity_v"):
        sanity_sweep()
    where, a = ["score>=?"], [rules.tf(args.get("min"), 0)]
    if args.get("platform"):
        where.append("platform=?"); a.append(args["platform"])
    if args.get("cat"):
        where.append("category=?"); a.append(args["cat"])
    if str(args.get("ex")) != "1" and not args.get("gk"):
        where.append("excluded=''")
    if str(args.get("new")) == "1":
        where.append("new_at>=?"); a.append(db.day_start())
    if args.get("watch"):
        where.append("watch_id=?"); a.append(int(rules.tf(args["watch"])))
    if str(args.get("bad")) == "1":
        where.append("capture_bad<>''")
    if args.get("q"):
        where.append("(title LIKE ? OR author LIKE ?)"); a += [f"%{args['q']}%"] * 2
    gk = [x for x in str(args.get("gk") or "").split(",") if x]
    alert = rules.tf(load_config().get("cur_alert_score"), 70)
    idx, gn = pool.group_index(alert)
    if gk:                                        # v2.53 自动分组：几个并起来；这时状态由分组决定
        ok_ids = [i for i, g in idx.items() if all(x in g for x in gk)]
        where.append(f"id IN ({','.join(str(int(i)) for i in ok_ids) or '0'})")
    st = "all" if gk else (args.get("status") or "open")
    if st == "open":
        where.append("status=''")
    elif st != "all":
        where.append("status=?"); a.append(st)
    rows = c.execute(f"SELECT * FROM cur_candidates WHERE {' AND '.join(where)} ORDER BY score DESC, last_seen DESC LIMIT 300", a).fetchall()
    cfg = load_config()
    from . import demand
    dem = demand.matcher()
    out = []
    for r in rows:
        b = badge(r, cfg)
        b.update(id=r["id"], url=r["url"], title=r["title"], thumb=r["thumb"], author=r["author"], platform=r["platform"],
                 platform_name=sites.name_of(r["platform"]), metrics=db.jl(r["metrics"]), new=r["new_at"] >= db.day_start(),
                 watch_id=r["watch_id"], last_seen=r["last_seen"], market=dem(r["title"], (db.jl(r["ai"]).get("thai_keywords") or []), r["category"]))
        out.append(b)
    t0 = db.day_start()
    k = {"total": c.execute("SELECT COUNT(*) FROM cur_candidates").fetchone()[0],
         "good": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE excluded='' AND score>=? AND status=''",
                           (rules.tf(cfg.get("cur_alert_score"), 70),)).fetchone()[0],
         "new_today": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE new_at>=? AND excluded=''", (t0,)).fetchone()[0],
         "excluded": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE excluded<>''").fetchone()[0],
         "bad": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE capture_bad<>'' AND product_id=''").fetchone()[0],
         "wait_ai": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE ai_at=0 AND ai_error='' AND capture_bad=''").fetchone()[0] if ai_on(cfg) else 0}
    hist = [0] * 10
    for r in c.execute("SELECT score FROM cur_candidates WHERE excluded=''"):
        hist[min(9, int(r[0] // 10))] += 1
    reasons = [{"reason": r[0], "reason_th": rules.REASON_TH.get(r[0], ""), "n": r[1]}
               for r in c.execute("SELECT excluded, COUNT(*) FROM cur_candidates WHERE excluded<>'' GROUP BY excluded ORDER BY 2 DESC LIMIT 6")]
    cats = [{"name": r[0], "th": rules.CATEGORY_TH.get(r[0], r[0])} for r in c.execute("SELECT DISTINCT category FROM cur_candidates WHERE category<>'' ORDER BY category")]
    res = {"rows": out, "kpi": k, "radar": demand.has_radar(), "hist": hist, "reasons": reasons, "cats": cats, "ai": ai_on(cfg), "calib": calib(),
           "alert_score": rules.tf(cfg.get("cur_alert_score"), 70)}
    res["groups"] = pool.summary(gn)
    res["pool"] = pool.kpis()
    if not owner:
        for r in res["rows"]:
            r["parts"].pop("profit", None)
            r.pop("price", None)
    return res


def set_status(ids, status):
    if status not in ("", "ignored", "later", "seen"):
        raise ValueError("状态不对")
    if status == "seen":
        return pool.set_seen(ids)
    c = db.conn()
    c.executemany("UPDATE cur_candidates SET status=?, seen_at=CASE WHEN ?<>'' THEN ? ELSE seen_at END WHERE id=? AND status<>'adopted'",
                  [(status, status, time.time(), int(i)) for i in ids])
    c.commit()
