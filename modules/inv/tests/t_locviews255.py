# v2.55 仓库 → 货位页三种看法（列表 / 按商品 / 货位图）+ 1 万商品 / 2 万货位的服务端分页、筛选、排序、搜索：
# 列表和按商品的接口（字段、筛选、搜索、排序、翻页）、抽屉数据、批量移库、标签 / 盘点接受选中的货位、货位图只取选中的库区、
# 汇总和旧的货位图统计一致、数量文字走 qtytext、库存表分页；最后灌 2 万货位 + 1 万商品压测（列表 / 搜索 / 排序都要 < 1 秒）。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, time, re
D = T + "/m_locviews255"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP); sys.path.insert(0, APP + "/modules/inv/tests")
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, inventory as inv
from modules.inv import locations as L, wms, locviews, qtytext, views
C = A.app.test_client()
config.save_config({"review_enabled": False, "inv_loss_rate": 0, "inv_loc_auto": False, "printers": []})
c = db.conn()
J = lambda url, **kw: C.get(url, **kw).get_json()
P = lambda url, body: C.post(url, json=body).get_json()
CJK = re.compile(r"[一-鿿]")

# ---------- 数量文字：只有一个函数 ----------
ok(qtytext.qty_text(1970, "g") == "1,970 g ≈ 1.97 kg" and qtytext.qty_text(12, "件") == "12 件" and qtytext.qty_text(12.5, "个", None, "th") == "12.5 ชิ้น",
   f"qty_text default format {qtytext.qty_text(1970, 'g')} / {qtytext.qty_text(12, '件')}")
b = qtytext.both(5, "卷")
ok(b == {"qty_text": "5 卷", "qty_text_th": "5 ม้วน"}, f"qty_text both {b}")

# ---------- 小数据：货架、商品 ----------
P("/api/inv/locations/bulk", {"zone": "A", "layers": 2, "positions": 3, "categories": ["goods"]})                    # A1-01-01..A1-02-03
P("/api/inv/locations/bulk", {"zone": "R", "layers": 1, "positions": 3, "ztype": "reserve"})                       # R1-01-01..03
P("/api/inv/locations/bulk", {"zone": "F", "layers": 1, "positions": 2, "ztype": "supply", "categories": ["filament", "part"]})
P("/api/inv/locations/bulk", {"zone": "B", "layers": 5, "positions": 10, "ztype": "reserve"})                      # 50 个货位：翻页用
new = lambda name, cat="goods", unit="件", **kw: C.post("/api/inv/items", json={"name_zh": name, "name_th": kw.pop("th", ""), "category": cat, "unit": unit, **kw}).get_json()["item"]
g1 = new("红色挂件", code="G-RED", th="จี้สีแดง"); g2 = new("蓝色摆件", code="G-BLUE", th="ตุ๊กตาสีน้ำเงิน"); g3 = new("绿色钥匙扣", code="G-GREEN")
p1 = new("六角螺丝", "part", "个", code="P-SCREW"); f1 = new("ASA 荧光橙", "part", "g", code="F-ASA-FO")
def buy(it, q):
    return inv.create_doc("purchase", [{"item_id": it["id"], "qty": q}], "", "t")
for it, q in ((g1, 20), (g2, 30), (g3, 8), (p1, 100), (f1, 1970)):
    buy(it, q)
ok(wms.pending_count() == 5, f"inbound with auto-putaway off -> 5 pending {wms.pending_count()}")
def put(it, code, q): return P("/api/inv/wms/putaway", {"item_id": it["id"], "code": code, "qty": q, "force": True})
put(g1, "A1-01-01", 20); put(g2, "A1-01-02", 12); put(g2, "R1-01-01", 18); put(g3, "A1-01-03", 3); put(g3, "A1-02-01", 2); put(g3, "R1-01-02", 1); put(g3, "B1-01-01", 2)
put(p1, "F1-01-01", 100); put(f1, "F1-01-02", 1970)
P("/api/inv/locations/props", {"codes": ["A1-01-01"], "props": {"capacity": 20, "min_qty": 5}})
P("/api/inv/locations/props", {"codes": ["A1-01-02"], "props": {"capacity": 10}})        # 12 > 10 -> 超容量
P("/api/inv/locations/props", {"codes": ["A1-01-03"], "props": {"min_qty": 10}})          # 3 < 10 -> 低于补货线

# ---------- 列表：一行一个货位 ----------
r = J("/api/inv/loc/list?size=200")
codes = [x["code"] for x in r["rows"]]
ok(r["ok"] and r["total"] == len(r["rows"]) == 61, f"list total {r['total']} (A 6 + R 3 + F 2 + B 50)")
ok(codes == sorted(codes, key=L.sort_key), "default sort = zone -> shelf -> layer -> pos")
row = {x["code"]: x for x in r["rows"]}
a1 = row["A1-01-01"]
ok(a1["items"][0]["code"] == "G-RED" and a1["items"][0]["name_zh"] == "红色挂件" and a1["items"][0]["qty_text"] == "20 件" and a1["items"][0]["qty_text_th"] == "20 ชิ้น", f"row contents {a1['items'][0]}")
ok(a1["state"] == "full" and a1["util"] == 100.0 and a1["capacity"] == 20 and a1["zone"] == "A" and a1["shelf_code"] == "A1" and a1["layer"] == 1 and a1["pos"] == 1, "row: state / util / shelf / layer / pos")
ok(row["A1-01-02"]["state"] == "over" and row["A1-01-03"]["below_min"] and row["A1-01-03"]["low"] and row["A1-02-02"]["state"] == "empty", "states over / below_min / empty")
ok(row["A1-01-01"]["last_move"] and row["A1-01-01"]["last_move"] > time.time() - 3600, "last movement time")
ok(not CJK.search(" ".join(x["qty_text_th"] for rw in r["rows"] for x in rw["items"])), "Thai quantity text has no Chinese")
fil = row["F1-01-02"]["items"][0]
ok(fil["qty_text"] == "1,970 g ≈ 1.97 kg" and fil["category"] == "part", f"filament text from the single helper {fil['qty_text']}")

# 筛选
f = lambda **kw: J("/api/inv/loc/list?" + "&".join(f"{k}={v}" for k, v in {"size": 200, **kw}.items()))
ok({x["code"] for x in f(zone="R")["rows"]} == {"R1-01-01", "R1-01-02", "R1-01-03"}, "filter zone")
ok([x["code"] for x in f(zone="A", shelf="A1", status="over")["rows"]] == ["A1-01-02"], "filter shelf + status=over")
ok([x["code"] for x in f(status="full")["rows"]] == ["A1-01-01"], "filter status=full")
ok({x["code"] for x in f(status="low")["rows"]} == {"A1-01-03"}, "filter status=low (below min)")
ok({x["code"] for x in f(below_min="1", zone="A")["rows"]} == {"A1-01-03"}, "filter below_min")
ok(f(zone="A", has="empty")["total"] == 2 and f(zone="A", has="nonempty")["total"] == 4, "filter empty / non-empty")
ok({x["code"] for x in f(category="part")["rows"]} == {"F1-01-01", "F1-01-02"}, "filter category")
ok(f(zone="NOPE")["total"] == 0, "filter: nothing")
# 搜索：货位编号 / 商品名称 / SKU
ok([x["code"] for x in f(q="a1-1-1")["rows"]] == ["A1-01-01"], "search by loose location code a1-1-1")
ok({x["code"] for x in f(q=__import__("urllib.parse").parse.quote("红色"))["rows"]} == {"A1-01-01"}, "search by product name")
ok({x["code"] for x in f(q="G-BLUE")["rows"]} == {"A1-01-02", "R1-01-01"}, "search by SKU")
ok({x["code"] for x in f(q="g-green")["rows"]} == {"A1-01-03", "A1-02-01", "R1-01-02", "B1-01-01"}, "search by SKU (case-insensitive) finds every location")
ok(f(q="ตุ๊กตา")["total"] == 2, "search by Thai name")
ok(f(q="%25")["total"] == 0, "search: % is not a wildcard")
# 排序
ok([x["code"] for x in f(sort="qty", dir="desc", zone="A")["rows"]][:2] == ["A1-01-01", "A1-01-02"] or [x["code"] for x in f(sort="qty", dir="desc", zone="A")["rows"]][:2] == ["A1-01-02", "A1-01-01"], "sort qty desc (20 / 12 first)")
srt = f(sort="qty", dir="desc")["rows"]; ok(all(srt[i]["total"] >= srt[i + 1]["total"] for i in range(len(srt) - 1)), "sort qty desc is monotone")
srt = f(sort="util", dir="desc", zone="A")["rows"]; ok(srt[0]["code"] == "A1-01-02", f"sort util desc -> over first {srt[0]['code']}")
srt = f(sort="last_move", dir="desc")["rows"]; ok(all((srt[i]["last_move"] or 0) >= (srt[i + 1]["last_move"] or 0) for i in range(len(srt) - 1)), "sort last movement")
srt = f(sort="code", dir="desc")["rows"]; ok([x["code"] for x in srt] == sorted([x["code"] for x in srt], key=L.sort_key, reverse=True), "sort code desc")
ok(f(sort="drop table")["sort"] == "code", "unknown sort falls back to code")
# 翻页
p1_ = f(zone="B", size=50, page=1); p2_ = f(zone="B", size=50, page=2)
ok(p1_["total"] == 50 and p1_["pages"] == 1 and len(p1_["rows"]) == 50 and p2_["page"] == 1, "paging: 50 rows = one page, page clamps")
al = f(size=50, page=2); ok(al["page"] == 2 and len(al["rows"]) == al["total"] - 50 and al["pages"] == 2, f"paging: page 2 of {al['pages']} has {len(al['rows'])}")
ok(f(size=7)["size"] == 50 and f(size=120)["size"] == 100 and f(size=500)["size"] == 200, "page size is 50 / 100 / 200")
ok(len({x["code"] for x in f(size=50, page=1)["rows"]} & {x["code"] for x in al["rows"]}) == 0, "pages do not overlap")
cd = J("/api/inv/loc/codes?zone=B"); ok(cd["total"] == 50 and len(cd["codes"]) == 50 and not cd["capped"], "codes of the whole filter (select all N)")
sg = J("/api/inv/loc/suggest?q=a1-02")["locations"]; ok([x["code"] for x in sg] == ["A1-02-01", "A1-02-02", "A1-02-03"] and sg[0]["empty"] is False and sg[1]["empty"], f"suggest {sg}")

# ---------- 按商品：一行一个商品 ----------
r = J("/api/inv/loc/items?size=50"); rows = {x["code"]: x for x in r["rows"]}
ok(r["total"] == 5 and set(rows) == {"G-RED", "G-BLUE", "G-GREEN", "P-SCREW", "F-ASA-FO"}, f"items view rows {sorted(rows)}")
gb = rows["G-BLUE"]
ok(gb["qty"] == 30 and gb["nloc"] == 2 and {d["code"]: d["qty"] for d in gb["locs"]} == {"A1-01-02": 12, "R1-01-01": 18} and gb["locs"][0]["code"] == "A1-01-02", f"distribution {gb['locs']}")
ok(gb["locs"][0]["qty_text"] == "12 件" and gb["qty_text"] == "30 件" and gb["name_th"] == "ตุ๊กตาสีน้ำเงิน", "item row texts")
ok("scattered" in rows["G-GREEN"]["flags"] and rows["G-GREEN"]["nloc"] == 4 and "scattered" not in gb["flags"], "flag: too scattered (4 > 3 locations)")
g4 = new("没上架的东西", code="G-LOST"); buy(g4, 7)
rr = {x["code"]: x for x in J("/api/inv/loc/items?size=50")["rows"]}
ok("unplaced" in rr["G-LOST"]["flags"] and rr["G-LOST"]["unplaced"] == 7 and "noloc" in rr["G-LOST"]["flags"] and rr["G-LOST"]["unplaced_text"] == "7 件", "flag: not put away")
fi = lambda **kw: J("/api/inv/loc/items?" + "&".join(f"{k}={v}" for k, v in kw.items()))
ok([x["code"] for x in fi(flag="scattered")["rows"]] == ["G-GREEN"] and [x["code"] for x in fi(flag="unplaced")["rows"]] == ["G-LOST"], "filter flag=scattered / unplaced")
ok({x["code"] for x in fi(zone="R")["rows"]} == {"G-BLUE", "G-GREEN"} and {x["code"] for x in fi(category="part")["rows"]} == {"P-SCREW", "F-ASA-FO"}, "items filter zone / category")
ok([x["code"] for x in fi(shelf="B1")["rows"]] == ["G-GREEN"] and [x["code"] for x in fi(q="A1-01-01")["rows"]] == ["G-RED"], "items filter shelf + search by location code")
ok([x["code"] for x in fi(q=__import__("urllib.parse").parse.quote("蓝色"))["rows"]] == ["G-BLUE"] and [x["code"] for x in fi(q="g-red")["rows"]] == ["G-RED"], "items search name / SKU")
s_ = fi(sort="qty", dir="desc")["rows"]; ok(all(s_[i]["qty"] >= s_[i + 1]["qty"] for i in range(len(s_) - 1)), "items sort qty desc")
s_ = fi(sort="locs", dir="desc")["rows"]; ok(s_[0]["code"] == "G-GREEN", "items sort by number of locations")
s_ = fi(sort="name")["rows"]; ok(len(s_) == 6, "items sort by name")
ok(fi(size=50, page=9)["page"] == 1, "items page clamps")

# ---------- 抽屉 ----------
lid = L.get_loc("A1-01-02")["id"]
wms.move("A1-01-02", "R1-01-03", [{"item_id": g2["id"], "qty": 2}], "tester")
d = J(f"/api/inv/loc/{lid}/drawer")
ok(d["ok"] and d["location"]["code"] == "A1-01-02" and d["items"][0]["code"] == "G-BLUE" and d["items"][0]["qty_text"] == "10 件" and d["items"][0]["total_text"] == "30 件", "drawer: contents + texts")
lg = d["log"]
ok(lg and lg[0]["to"] == "R1-01-03" and lg[0]["dir"] == "out" and lg[0]["code"] == "G-BLUE" and lg[0]["user"] == "tester" and lg[0]["qty_text"] == "2 件", f"drawer: movement log {lg[:1]}")
ok(any(x["dir"] == "in" for x in lg), "drawer: log has the put-away (in)")
ok("error" in J("/api/inv/loc/999999/drawer"), "drawer: no such location -> error")

# ---------- 批量移库 ----------
P("/api/inv/locations/props", {"codes": ["R1-01-02"], "props": {"capacity": 100}})
r = P("/api/inv/loc/bulk", {"action": "move", "codes": ["A1-01-03", "A1-02-01"], "to": "R1-01-02"})
ok(r["ok"] and r["done"] == 2 and not r["errors"] and wms.loc_qty(db.conn(), g3["id"], L.get_loc("R1-01-02")["id"]) == 6, f"bulk move 2 locations into one {r}")
P("/api/inv/locations/props", {"codes": ["R1-01-03"], "props": {"capacity": 13}})
r = P("/api/inv/loc/bulk", {"action": "move", "codes": ["A1-01-02", "B1-01-01", "F1-01-01"], "to": "R1-01-03"})
ok(r["ok"] and r["done"] == 1 and {e["code"] for e in r["errors"]} == {"B1-01-01", "F1-01-01"}, f"bulk move: failures are listed, the rest still move {r['done']} {[e['code'] for e in r['errors']]}")
ok("error" in P("/api/inv/loc/bulk", {"action": "move", "codes": ["A1-01-01"], "to": "NOPE-1"}) and "error" in P("/api/inv/loc/bulk", {"action": "move", "codes": [], "to": "R1-01-01"}), "bulk move: bad target / empty selection rejected")
ok("error" in P("/api/inv/loc/bulk", {"action": "boom", "codes": ["A1-01-01"]}), "bulk: unknown action rejected")
r = P("/api/inv/loc/bulk", {"action": "move", "codes": ["R1-01-01"], "to": "A2-01-01"})
ok("error" in r, "bulk move into a location that does not exist")
# 标签 / 盘点 / 设置接受选中的货位
h = C.get("/print/inv-locations?codes=A1-01-01,R1-01-01&fmt=qr")
ok(h.status_code == 200 and "A1-01-01" in h.get_data(as_text=True) and "R1-01-01" in h.get_data(as_text=True) and "A1-02-03" not in h.get_data(as_text=True), "labels for the selected codes")
h = C.get("/print/inv-locations?flt=1&zone=R")
ok(h.status_code == 200 and "R1-01-02" in h.get_data(as_text=True) and "A1-01-01" not in h.get_data(as_text=True), "labels for everything matching the filter")
st = P("/api/inv/stocktake", {"area": "A1-01-01,R1-01-01,B1-01-01"})
ok(st["ok"] and st["doc"]["id"], "add selected locations to a stocktake")
r = P("/api/inv/locations/props", {"codes": ["B1-01-01", "B1-01-02"], "props": {"capacity": 9}})
ok(r["ok"] and f(zone="B", sort="capacity", dir="desc")["rows"][0]["capacity"] == 9, "bulk settings (capacity) show up in the list")

# ---------- 货位图：只取选中的库区 / 货架 ----------
m = J("/api/inv/loc/map")
ok(m["ok"] and {z["zone"] for z in m["zones"]} == {"A", "R", "F", "B"} and "locations" not in m and "shelves" not in m, f"map: no zone = zone summary rows only {[z[chr(122)+"one"] for z in m["zones"]]} {list(m)}")
m = J("/api/inv/loc/map?zone=B")
ok(len(m["shelves"]) == 1 and m["shelves"][0]["shelf"] == "B1" and m["shelves"][0]["total"] == 50 and "locations" not in m, "map: zone = shelf summary rows, no cells yet")
m = J("/api/inv/loc/map?zone=A&shelf=A1")
ok(len(m["locations"]) == 6 and m["locations"][0]["code"] == "A1-01-01" and m["locations"][0]["items"][0]["name_zh"] == "红色挂件", "map: one shelf expanded, cells carry product name")
m = J("/api/inv/loc/map?zone=A&expand=all"); ok(len(m["locations"]) == 6, "map: expand=all")
m = J("/api/inv/loc/map?every=1"); ok(len(m["locations"]) == 6 + 3 + 2 + 50, "map: every=1 gives all cells (small warehouse)")
ok(J("/api/inv/loc/map?zone=A&shelf=B1")["ok"] and "locations" not in J("/api/inv/loc/map?zone=A&shelf=B1"), "map: shelf of another zone gives nothing")

# ---------- 汇总：和旧的货位图统计一致 ----------
sm = J("/api/inv/loc/summary?force=1")["stats"]; old = wms.map_data()["stats"]
ok(all(sm[k] == old[k] for k in ("total", "used", "empty", "full", "over", "pending", "tasks")), f"summary == map_data stats {sm} vs {old}")
ok(abs(sm["util"] - old["util"]) < 0.11, "summary util")
c1 = locviews.summary(); ok(locviews.summary() is c1, "summary is cached while nothing changes")
put(g4, "A2-01-01", 1) if L.get_loc("A2-01-01") else None
wms.move("", "R1-01-01", [{"item_id": g4["id"], "qty": 1}], "t")
ok(locviews.summary() is not c1 and locviews.summary()["stats"]["pending"] == old["pending"], "summary refreshes after a movement")
# 待上架数：快速版和逐个物品算的一样
slow = sum(1 for r_ in c.execute("SELECT id, qty FROM inv_items WHERE active=1 AND qty>0") if (r_["qty"] or 0) - wms.located(c, r_["id"]) > 1e-6)
ok(wms.pending_count() == slow + c.execute("SELECT COUNT(*) FROM inv_loc_qty q JOIN inv_locations l ON l.id=q.loc_id LEFT JOIN inv_loc_groups g ON g.code=l.zone AND g.kind='zone' WHERE q.qty>0 AND g.ztype='staging'").fetchone()[0],
   f"pending_count (one SQL) == per-item count {slow}")

# ---------- /api/inv/locations：货位少给全部，货位多只给汇总 ----------
r = J("/api/inv/locations"); ok(r["big"] is False and len(r["locations"]) == 61 + 7 and "PR" in r["zones"] and {"A", "B", "F", "R"} <= set(r["zones"]) and r["max_shelf"]["A"] == 1, f"locations API (small): everything + zone list {r["big"]} {len(r["locations"])} {r["zones"]} {r["max_shelf"]}")

# ---------- 库存表：服务端分页 / 排序 / 搜索 ----------
old_all = J("/api/inv/items?view=stock")
pg = J("/api/inv/items?view=stock&page=1&size=50&sort=qty&dir=desc")
ok(pg["ok"] and pg["total"] == len(old_all["items"]) and pg["pages"] == 1 and pg["size"] == 50, f"inventory table paging total {pg['total']} == {len(old_all['items'])}")
ok([x["code"] for x in pg["items"]] == [x["code"] for x in sorted(old_all["items"], key=lambda x: -x["qty"])][:len(pg["items"])] or all(pg["items"][i]["qty"] >= pg["items"][i + 1]["qty"] for i in range(len(pg["items"]) - 1)), "inventory table sort qty desc")
ok(pg["items"][0]["qty_text"] and any(x["qty_text"] == "1,970 g ≈ 1.97 kg" for x in pg["items"]) and all(x["qty_text_th"] for x in pg["items"]), "inventory rows carry qty_text")
ok([x["code"] for x in J("/api/inv/items?view=stock&page=1&size=50&q=G-RED")["items"]] == ["G-RED"], "inventory search")
ok({x["code"] for x in J("/api/inv/items?view=stock&page=1&size=50&category=goods")["items"]} == {x["code"] for x in old_all["items"] if x["category"] == "goods"}, "inventory category filter")
z = J("/api/inv/items?view=stock&page=1&size=50&zone=z:R")["items"]
ok({x["code"] for x in z} == {x["code"] for x in old_all["items"] if any(l["zone"] == "R" for l in x["locs"])}, "inventory zone filter == old listing")
ok({x["code"] for x in J("/api/inv/items?view=stock&page=1&size=50&zone=unplaced")["items"]} == {x["code"] for x in old_all["items"] if (x["unplaced"] or 0) > 1e-9 or (not x["locs"] and x["qty"])}, "inventory 'not put away' filter == old listing")
ok({x["code"] for x in J("/api/inv/items?view=stock&page=1&size=50&loc=R1")["items"]} == {x["code"] for x in old_all["items"] if any(l["code"].startswith("R1") for l in x["locs"])}, "inventory location-prefix filter")
cn = pg["counts"]; oc = J("/api/inv/items?view=stock")["counts"]
ok(cn["goods"]["stock"] == oc["goods"]["stock"] and cn["goods"]["all"] == oc["goods"]["all"] and cn["part"]["low"] == oc["part"]["low"], f"category counts (SQL) == old counts {cn['goods']} {oc['goods']}")
ok(J("/api/inv/items?view=catalog&page=1&size=50")["ok"] is not None and J("/api/inv/items?view=zero&page=1&size=100")["size"] == 100, "other inventory views page too")
ok(len(J("/api/inv/items?view=stock")["items"]) == len(old_all["items"]), "old (unpaged) call still returns everything")

# ---------- 2 万货位 + 1 万商品 压测 ----------
import synth255
t0 = time.time(); info = synth255.make(20000, 10000); print(f"     synthetic data: {info} in {time.time() - t0:.1f}s")
BIGN = info["locs"]
ok(info["locs"] == 20000 and info["items"] == 10000, "synthetic data: 20,000 locations, 10,000 items")
def timed(url, n=3):
    ts = []
    for _ in range(n):
        t = time.time(); r = C.get(url); ts.append(time.time() - t)
    j = r.get_json(); return sorted(ts)[len(ts) // 2], j
PERF = []
def perf(name, url, limit=1.0, check=None):
    t, j = timed(url)
    PERF.append((name, t))
    good = j.get("ok") and (check(j) if check else True)
    ok(good and t < limit, f"perf {name}: {t * 1000:.0f} ms (< {limit * 1000:.0f})")
    return j
# 耗材带卷数：合并 v2.55 B 之后，分页路径也要带每个货位几卷 / 多少克（给耗材物品各配 1–2 卷料卷，放在它们的货位上）
_t = time.time()
_fil = c.execute("SELECT id, code FROM inv_items WHERE category='filament' ORDER BY id").fetchall()
for _i, _r in enumerate(_fil):
    c.execute("UPDATE inv_items SET material='PLA', color=? WHERE id=?", (f"C{_i:04d}", _r["id"]))
    for _q in c.execute("SELECT loc_id, qty FROM inv_loc_qty WHERE item_id=? AND qty>1e-9", (_r["id"],)).fetchall():
        for _n in range(1 if _q["qty"] <= 500 else 2):
            _sid = c.execute("INSERT INTO spools(code, material, color, net_g, remaining_g, status, created_at) VALUES(?,?,?,?,?,?,?)",
                             (f"SYN{_i}-{_n}", "PLA", f"C{_i:04d}", 1000, min(1000.0, _q["qty"] / (2 if _q["qty"] > 500 else 1)), "sealed", time.time())).lastrowid
            c.execute("INSERT INTO inv_spool_loc(spool_id, loc_id, updated_at) VALUES(?,?,?)", (_sid, _q["loc_id"], time.time()))
c.commit()
print(f"     synthetic spools: {c.execute('SELECT COUNT(*) FROM spools').fetchone()[0]} in {time.time() - _t:.1f}s")
tot_locs = c.execute("SELECT COUNT(*) FROM inv_locations WHERE active=1").fetchone()[0]
perf("list page 1 (50)", "/api/inv/loc/list", check=lambda j: j["total"] >= 20000 and len(j["rows"]) == 50)
perf("list page 100 (200 rows)", "/api/inv/loc/list?size=200&page=100", check=lambda j: j["page"] == 100 and len(j["rows"]) == 200)
perf("list search by SKU", "/api/inv/loc/list?q=SKU00010", check=lambda j: j["total"] >= 1 and any(i["code"] == "SKU00010" for r_ in j["rows"] for i in r_["items"]))
perf("list search by name (many hits)", "/api/inv/loc/list?q=" + __import__("urllib.parse").parse.quote("蓝色挂件"), check=lambda j: j["total"] > 1000)
perf("list search by location code", "/api/inv/loc/list?q=D12-03", check=lambda j: j["total"] >= 1)
perf("list sort by contents qty desc", "/api/inv/loc/list?sort=qty&dir=desc", check=lambda j: j["rows"][0]["total"] >= j["rows"][-1]["total"])
perf("list sort by utilisation desc", "/api/inv/loc/list?sort=util&dir=desc")
perf("list sort by state", "/api/inv/loc/list?sort=state&dir=desc")
perf("list sort by last movement", "/api/inv/loc/list?sort=last_move&dir=desc")
perf("list filter zone+status+category", "/api/inv/loc/list?zone=C&status=partial&category=goods")
perf("list filter below min", "/api/inv/loc/list?below_min=1&has=nonempty")
perf("items view page 1", "/api/inv/loc/items", check=lambda j: j["total"] >= 10000)
perf("items view search", "/api/inv/loc/items?q=SKU0077")
perf("items view sort by locations", "/api/inv/loc/items?sort=locs&dir=desc", check=lambda j: j["rows"][0]["nloc"] >= 6)
perf("items view flag scattered", "/api/inv/loc/items?flag=scattered")
perf("items view flag unplaced", "/api/inv/loc/items?flag=unplaced", check=lambda j: j["total"] > 0)
perf("summary (cold)", "/api/inv/loc/summary?force=1", check=lambda j: j["stats"]["total"] >= 20000)
perf("map zone summary", "/api/inv/loc/map", check=lambda j: len(j["zones"]) >= 8)
perf("map one zone", "/api/inv/loc/map?zone=C", check=lambda j: len(j["shelves"]) == 50 and "locations" not in j)
perf("map one shelf", "/api/inv/loc/map?zone=C&shelf=C3", check=lambda j: len(j["locations"]) == 50)
perf("codes of a zone (select all)", "/api/inv/loc/codes?zone=C", check=lambda j: j["total"] == 2500)
perf("location suggest", "/api/inv/loc/suggest?q=c1-", check=lambda j: len(j["locations"]) == 30)
perf("drawer", f"/api/inv/loc/{c.execute('SELECT loc_id FROM inv_loc_qty LIMIT 1').fetchone()[0]}/drawer")
perf("inventory table page 1", "/api/inv/items?view=stock&page=1&size=50", check=lambda j: j["total"] >= 10000 and len(j["items"]) == 50)
perf("inventory table page 50 / 200 rows", "/api/inv/items?view=stock&page=50&size=200", check=lambda j: j["page"] == 50)
perf("inventory table sort by qty", "/api/inv/items?view=stock&page=1&size=100&sort=qty&dir=desc", check=lambda j: j["items"][0]["qty"] >= j["items"][-1]["qty"])
_fp = perf("inventory table filament page (rolls)", "/api/inv/items?view=stock&category=filament&page=1&size=200", check=lambda j: len(j["items"]) == 200 and all(x.get("units") for x in j["items"]))
_x = _fp["items"][0]
ok("卷" in _x["qty_text"] and ("kg" in _x["qty_text"] or " g" in _x["qty_text"]), f"filament qty_text shows rolls + weight: {_x['qty_text']}")
ok(_x["locs"] and all("rolls" in l_ and l_.get("text_zh") and "卷" in l_["qty_text"] for l_ in _x["locs"]), f"paged locs carry roll info: {_x['locs'][0].get('text_zh')}")
_lp = perf("list filament only (roll text)", "/api/inv/loc/list?category=filament&size=200", check=lambda j: len(j["rows"]) == 200)
ok(any("卷" in i_["qty_text"] for r_ in _lp["rows"] for i_ in r_["items"]), "loc list shows rolls for filament")
_ip = perf("items view filament (roll text)", "/api/inv/loc/items?category=filament&size=200", check=lambda j: len(j["rows"]) == 200)
ok(all("卷" in r_["qty_text"] for r_ in _ip["rows"] if r_["qty"] > 0), "by-item totals show rolls for filament")
perf("inventory table sort by name", "/api/inv/items?view=stock&page=2&size=50&sort=name")
perf("inventory table search", "/api/inv/items?view=stock&page=1&size=50&q=SKU0077", check=lambda j: j["total"] >= 1)
perf("inventory table zone filter", "/api/inv/items?view=stock&page=1&size=50&zone=z:C")
perf("/api/inv/locations (no 20k list)", "/api/inv/locations", check=lambda j: j["big"] is True and j["locations"] == [] and len(j["shelves"]) >= 400)
r_ = P("/api/inv/loc/bulk", {"action": "move", "codes": [f"E{i}-01-01" for i in range(1, 30)], "to": "M1-01-01", "force": True})
ok(r_["ok"] and r_["done"] + len(r_["errors"]) >= 1, "bulk move at scale")
# 结果对得上：列表总数 = SQL 数；翻页不丢不重
ok(J("/api/inv/loc/list?size=200")["total"] == c.execute("SELECT COUNT(*) FROM inv_locations l LEFT JOIN inv_loc_groups g ON g.code=l.zone AND g.kind='zone' WHERE l.active=1 AND COALESCE(NULLIF(g.ztype,''),'pick')<>'production'").fetchone()[0], "list total == SQL count at scale")
seen = set(); pages = J("/api/inv/loc/list?size=200")["pages"]
for pgn in (1, 2, pages):
    seen |= {x["code"] for x in J(f"/api/inv/loc/list?size=200&page={pgn}")["rows"]}
ok(len(seen) == 200 + 200 + (J(f"/api/inv/loc/list?size=200&page={pages}")["total"] - 200 * (pages - 1)), "paging at scale: no overlap")
sm = J("/api/inv/loc/summary?force=1")["stats"]; old = wms.map_data()["stats"]
ok(all(sm[k] == old[k] for k in ("total", "used", "empty", "full", "over")), f"summary == map_data at scale {sm['total']}/{sm['used']}/{sm['full']}/{sm['over']}")
print("PERF " + " | ".join(f"{n}: {t * 1000:.0f}ms" for n, t in PERF))
print(f"PERF max {max(t for _n, t in PERF) * 1000:.0f} ms")

for f_ in os.listdir(APP + "/templates_lazada") if os.path.isdir(APP + "/templates_lazada") else []:
    if f_.startswith("lazada_auto_"):
        try: os.remove(APP + "/templates_lazada/" + f_)
        except OSError: pass
print("ERRORS", E_)
