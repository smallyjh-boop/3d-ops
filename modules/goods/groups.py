"""产品库左边的自动分组（v2.53）：按产品资料 + 平台在线数据现算，不存，修好就自动离开。

每个产品得到一串分组键 item["gk"]：
  on:live / on:off            在线 / 未上线        on:<平台>:<店铺>   在线的店铺（平台 lazada / shopee，店铺名；没有店铺记录时店铺为空）
  pg:*   进度（互斥）          incomplete 资料不全 · print 待切片 / 待试打 · ready 可上架 · review 审核中 · live 在售 · down 已下架 / 被拒
  td:*   待处理（可叠加）      noimg noword nocat nograms noslice notest license rejected belowcost lowstock
  sl:*   销售表现（近 30 天）  hot slow new lowmargin
  ct:<类目路径前缀>  ct:none   类目；src:own / src:curate  来源
  mk:upload mk:edit           手动标记；tg:<标签编号>  自定义标签
summary() 一次扫完算各分组的个数。阈值在 core/prodgroups.settings()。
"""
import time

from core import prodgroups

PROGRESS = ("incomplete", "print", "ready", "review", "live", "down")
TODO = ("noimg", "noword", "nocat", "nograms", "noslice", "notest", "license", "rejected", "belowcost", "lowstock")
SALES = ("hot", "slow", "new", "lowmargin")


def _statuses(item):
    """这个产品在各平台的状态集合（平台在线商品表 + 上架模块记的状态）。"""
    st = {"live": False, "uploaded": False, "rejected": False, "inactive": False}
    for o in item.get("online") or []:
        s = o.get("status")
        if s in st:
            st[s] = True
    for k in ("lz", "sp"):
        s = (item.get(k) or {}).get("status")
        if s in ("live", "update"):
            st["live"] = True
        elif s in st:
            st[s] = True
    return st


def online_keys(item):
    """在线的店铺键：on:lazada:店铺A。在线商品表没有记录的平台，退回看上架模块记的「已上线」，店铺为空。"""
    keys, seen = [], set()
    for o in item.get("online") or []:
        if o.get("status") == "live":
            seen.add(o.get("platform"))
            keys.append(f"on:{o.get('platform')}:{o.get('shop') or ''}")
    for k, plat in (("lz", "lazada"), ("sp", "shopee")):
        if plat not in seen and (item.get(k) or {}).get("status") in ("live", "update"):
            keys.append(f"on:{plat}:")
    return sorted(set(keys))


def classify(item, p, errs, prices, cat_path, stock_min, first_live, S, now):
    """给一个产品算分组键（热销要全部产品比完才知道，在 finish() 里补）。"""
    gk = set()
    st = _statuses(item)
    live, up, rej, inact = st["live"], st["uploaded"], st["rejected"], st["inactive"]
    onl = online_keys(item)
    gk.update(onl)
    gk.add("on:live" if live else "on:off")
    # ---- 待处理 ----
    cp = p.get("copy") or {}
    has_model = bool(p.get("model"))
    fs = item.get("file_status")
    todo = set()
    if not p.get("images"):
        todo.add("noimg")
    if not (cp.get("title_th") and cp.get("description_th")):
        todo.add("noword")
    if not (p.get("category") or {}).get("id"):
        todo.add("nocat")
    if any(not float(v.get("grams") or 0) for v in p.get("variants") or []):
        todo.add("nograms")
    if has_model and fs not in ("reviewed", "verified"):
        todo.add("noslice")
    elif has_model and fs == "reviewed":
        todo.add("notest")
    if (p.get("license_check") or {}).get("status") == "pending":
        todo.add("license")
    if rej:
        todo.add("rejected")
    margins = [pr["profit"] / pr["final_price"] for pr in prices if pr.get("final_price")]
    if any(pr.get("profit", 0) < 0 for pr in prices):
        todo.add("belowcost")
    if live and stock_min is not None and stock_min < S["low_stock"]:
        todo.add("lowstock")
    gk.update("td:" + k for k in todo)
    # ---- 进度（互斥）：先看平台上的状态，没上平台再看资料 / 切片 ----
    if live:
        pg = "live"
    elif up:
        pg = "review"
    elif rej or inact:
        pg = "down"
    elif errs:
        pg = "incomplete"
    elif has_model and fs != "verified":
        pg = "print"
    else:
        pg = "ready"
    gk.add("pg:" + pg)
    # ---- 销售表现（热销在 finish() 补）----
    sold = item.get("sold30") or 0
    t0 = first_live or ((p.get("listing") or {}).get("lazada") or {}).get("first_listed_at") or ((p.get("listing") or {}).get("shopee") or {}).get("first_listed_at")
    if live and t0:
        age = (now - float(t0)) / 86400
        if age < S["new_days"]:
            gk.add("sl:new")
        if age > S["slow_days"] and not sold:
            gk.add("sl:slow")
    if live and margins and min(margins) * 100 < S["low_margin"]:
        gk.add("sl:lowmargin")
    # ---- 类目 / 来源 ----
    if cat_path:
        parts = [x.strip() for x in cat_path.split(">") if x.strip()]
        for i in range(1, len(parts) + 1):
            gk.add("ct:" + " > ".join(parts[:i]))
    else:
        gk.add("ct:none")
    gk.add("src:curate" if item.get("from_curator") else "src:own")
    # ---- 手动标记（上传成功了 / 已经在平台上，「要上传」就算清掉）----
    mk = p.get("marks") if isinstance(p.get("marks"), dict) else {}
    marks = {}
    for k in prodgroups.MARKS["goods"]:
        if k in mk and not (k == "upload" and (live or up)):
            marks[k] = {"note": (mk[k] or {}).get("note", ""), "at": (mk[k] or {}).get("at")}
            gk.add("mk:" + k)
    for g in p.get("groups") or []:
        gk.add(f"tg:{g}")
    item["marks"] = marks
    item["wmarks"] = {k: mk[k] for k in ("list", "price", "img") if k in mk}        # 上架工作台的标记（那边按店铺 / 完成情况算）
    item["gk"] = sorted(gk)
    item["cat_path"] = cat_path or ""


def finish(items, S):
    """热销：近 30 天卖出 ≥ 阈值，或排进前 N 名（至少卖出 1 件）。"""
    ranked = sorted((i for i in items if (i.get("sold30") or 0) > 0), key=lambda i: -(i.get("sold30") or 0))
    top = {i["id"] for i in ranked[:int(S["hot_top"])]}
    for i in items:
        s = i.get("sold30") or 0
        if s and (s >= S["hot_min"] or i["id"] in top):
            i["gk"] = sorted(set(i["gk"]) | {"sl:hot"})


def summary(items):
    """各分组的个数（一次扫完）+ 在线店铺列表 + 类目树。"""
    n = {}
    for i in items:
        for k in i["gk"]:
            n[k] = n.get(k, 0) + 1
    shops = sorted(({"key": k, "platform": k.split(":", 2)[1], "shop": k.split(":", 2)[2], "n": v} for k, v in n.items()
                    if k.startswith("on:") and k.count(":") == 2), key=lambda x: (-x["n"], x["key"]))
    paths = sorted(k[3:] for k in n if k.startswith("ct:") and k != "ct:none")
    tree = {}
    for pth in paths:
        parts = pth.split(" > ")
        node = tree
        for j in range(len(parts)):
            full = " > ".join(parts[:j + 1])
            node = node.setdefault(full, {"name": parts[j], "path": full, "n": n.get("ct:" + full, 0), "kids": {}})["kids"]

    def flat(d):
        return [dict(v, kids=flat(v["kids"])) for v in sorted(d.values(), key=lambda x: -x["n"])]
    return {"total": len(items), "n": n, "shops": shops, "cats": flat(tree)}
