"""测试 / 压测用：往当前数据库里一次灌进大量货位和物品（v2.55）。不是测试文件（文件名不以 t_ 开头，run_all 不会当测试跑）。

    make(n_loc=20000, n_items=10000, seed=7) → {"locs": 货位数, "items": 物品数, "placed": 货位上的行数}
8 个库区 C D E G H J K M（C D 拣货区、E G 备货区、H 耗材区、J K 包材区、M 退货区；避开测试自己用的 A B F R），每个库区 n_loc/8 个货位 = 50 个货架 × 5 层 × 10 位。
物品：70% 成品（SKU0001…）、5% 耗材（克）、15% 备件、10% 包材；每个物品放 1–3 个货位，个别物品故意不放满（待上架）或放得很散。"""
import random
import time

from core import db

ZONES = [("C", "pick"), ("D", "pick"), ("E", "reserve"), ("G", "reserve"), ("H", "supply"), ("J", "pack"), ("K", "pack"), ("M", "returns")]


def make(n_loc=20000, n_items=10000, seed=7):
    rnd = random.Random(seed)
    c = db.conn()
    now = time.time()
    per_zone = n_loc // len(ZONES)
    per_shelf = 50                                   # 5 层 × 10 位
    locs = []
    for z, zt in ZONES:
        c.execute("INSERT OR REPLACE INTO inv_loc_groups(code, kind, name, categories, updated_at, ztype) VALUES(?,?,?,?,?,?)", (z, "zone", f"{z} 库区", "", now, zt))
        k = 0
        for s in range(1, per_zone // per_shelf + 2):
            for ly in range(1, 6):
                for p in range(1, 11):
                    if k >= per_zone:
                        break
                    code = f"{z}{s}-{ly:02d}-{p:02d}"
                    cap = rnd.choice([None, 100, 200, 500]) if zt in ("pick", "reserve") else None
                    mn = rnd.choice([None, 10, 20]) if zt == "pick" else None
                    last = now - rnd.randint(0, 200) * 86400
                    locs.append((code, z, "", 1, now, s, ly, p, cap, None, 1, None, mn, last))
                    k += 1
    c.executemany("INSERT INTO inv_locations(code, zone, note, active, created_at, shelf, layer, pos, capacity, size, mixed, fixed_item, min_qty, last_move) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", locs)
    loc_ids = [r[0] for r in c.execute("SELECT id FROM inv_locations ORDER BY id")]
    loc_code = {r[0]: r[1] for r in c.execute("SELECT id, code FROM inv_locations")}
    items, placements = [], []
    cats = ["goods"] * 14 + ["filament"] + ["part"] * 3 + ["pack"] * 2
    for i in range(1, n_items + 1):
        cat = cats[(i - 1) % len(cats)]
        code = f"SKU{i:05d}" if cat == "goods" else f"{ {'filament': 'F-PLA-', 'part': 'BJ', 'pack': 'BC'}[cat] }{i:05d}"
        unit = "g" if cat == "filament" else "件" if cat == "goods" else "个"
        name_zh = f"测试{ {'goods': '商品', 'filament': '耗材', 'part': '备件', 'pack': '包材'}[cat] }{i:05d} 蓝色挂件"
        name_th = f"สินค้าทดสอบ {i:05d}"
        n = rnd.choice([1, 1, 1, 2, 2, 3]) if i % 997 else 6          # 个别物品放得很散
        where = rnd.sample(loc_ids, n)
        qs = [rnd.choice([5, 10, 20, 50, 100]) * (10 if unit == "g" else 1) for _ in where]
        total = sum(qs) + (rnd.choice([0, 0, 0, 7]) if i % 53 == 0 else 0)      # 个别物品有「待上架」的数量
        items.append((code, name_zh, name_th, cat, unit, total, round(rnd.uniform(1, 80), 2), rnd.choice([None, 5, 30]), loc_code[where[0]], 1, now, now,
                      "蓝色" if cat == "filament" else ""))
        placements.append((code, list(zip(where, qs))))
    c.executemany("INSERT INTO inv_items(code, name_zh, name_th, category, unit, qty, avg_cost, reorder_point, location, active, created_at, updated_at, color) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", items)
    iid = {r[0]: r[1] for r in c.execute("SELECT code, id FROM inv_items")}
    rows = [(iid[code], lid, q, now - rnd.randint(0, 100) * 86400) for code, ws in placements for lid, q in ws]
    c.executemany("INSERT OR REPLACE INTO inv_loc_qty(item_id, loc_id, qty, updated_at) VALUES(?,?,?,?)", rows)
    c.executemany("INSERT INTO inv_moves(ts, item_id, kind, qty, unit_cost, amount, balance, username) VALUES(?,?,?,?,?,?,?,?)",
                  [(now - 86400 * rnd.randint(1, 90), iid[code], "purchase", 1, 1, 1, 1, "synth") for code, _ in placements])
    c.executemany("INSERT INTO inv_loc_log(ts, item_id, from_loc, to_loc, qty, kind, username, ref) VALUES(?,?,?,?,?,?,?,?)",
                  [(now - 3600 * rnd.randint(1, 900), iid[code], "", loc_code[ws[0][0]], ws[0][1], "putaway", "synth", "") for code, ws in placements[:3000]])
    c.commit()
    from modules.inv import locviews
    locviews.invalidate()
    return {"locs": len(locs), "items": len(items), "placed": len(rows)}
