# v2.54.1：「随机颜色」/「多色」不再是粉红：预览 / 渲染都用中性暖浅灰；随机颜色的商品图右下角加角标（可关）；
# 颜色表可给随机 / 多色填预览颜色；模型尺寸显示不带浮点噪声。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import io, os, sys, shutil, sqlite3
D = T + "/m_colour254"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from PIL import Image, ImageChops
from core import db, store, codes, colorbadge, fmtnum
from core.config import load_config, save_config
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})

# ---------- 1. 颜色解析：随机 / 多色 → 中性灰 ----------
cfg = load_config()
ch = codes.color_hex(cfg)
ok(ch["随机颜色"]["hex"].lower() == codes.NEUTRAL_HEX.lower() and ch["多色"]["hex"].lower() == codes.NEUTRAL_HEX.lower(), f"随机 / 多色 → {ch['随机颜色']['hex']}")
ok(ch["随机颜色"]["random"] and ch["多色"]["random"] and not ch["白色"]["random"], "random flag on 随机颜色 / 多色 only")
ok(ch["彩虹渐变"]["code"] == "RB" and ch["彩虹渐变"]["hex"] == "#ff6b6b" and ch["大理石纹"]["hex"] == "#e9e7e3" and ch["木纹"]["hex"] == "#a0703f", "rainbow / marble / wood keep their own treatment")
r, g, b = Image.new("RGB", (1, 1), codes.NEUTRAL_HEX).getpixel((0, 0))
ok(max(r, g, b) - min(r, g, b) < 20 and r >= g >= b and 190 < r < 225, f"neutral grey is warm, light, not pink {(r, g, b)}")
ok(codes.render_hex(cfg, "随机颜色") == codes.NEUTRAL_HEX and codes.render_hex(cfg, "RND") == codes.NEUTRAL_HEX and codes.render_hex(cfg, "สีสุ่ม") == codes.NEUTRAL_HEX, "render_hex resolves by zh / code / th")
ok(codes.render_hex(cfg, "红色") == codes.COLOR_HEX["RD"] and codes.render_hex(cfg, "不存在的颜色") == codes.NEUTRAL_HEX, "real colours unchanged; unknown name → neutral")
# 旧版默认的粉红 / 非法值 = 没设置
tbl = [list(r) for r in codes.color_table(cfg)]
for r_ in tbl:
    if r_[1] == "RND": r_[:] = r_[:4] + ["#ff6b6b"]
save_config({"color_table": tbl})
ok(codes.color_hex(load_config())["随机颜色"]["hex"] == codes.NEUTRAL_HEX, "legacy pink override ignored")
# 设置里给随机 / 多色填预览颜色
for r_ in tbl:
    if r_[1] == "RND": r_[:] = r_[:4] + ["#AABBCC"]
    if r_[1] == "MC": r_[:] = r_[:4] + ["bad"]
save_config({"color_table": tbl})
ch = codes.color_hex(load_config())
ok(ch["随机颜色"]["hex"] == "#AABBCC" and ch["多色"]["hex"] == codes.NEUTRAL_HEX, "preview colour override on 随机颜色; invalid hex on 多色 → neutral")
ok(C.get("/api/colors").get_json()["随机颜色"]["hex"] == "#AABBCC", "/api/colors serves the override")
# 设置页保存：5 列合法 / 非法
lines = "\n".join(", ".join(r_[:4]) + (", " + r_[4] if len(r_) > 4 and r_[4] and r_[1] != "MC" else "") for r_ in tbl)
rs = C.post("/api/config", json={"color_table": lines.replace("#AABBCC", "#112233")})
ok(rs.status_code == 200 and codes.color_hex(load_config())["随机颜色"]["hex"] == "#112233", f"settings save keeps 5th column {rs.status_code}")
rs = C.post("/api/config", json={"color_table": lines.replace("#AABBCC", "pink")})
ok(rs.status_code == 400, f"settings reject a non-#RRGGBB preview colour {rs.status_code}")
tbl2 = [list(r) for r in tbl]
for r_ in tbl2:
    if r_[1] == "RND": r_[:] = r_[:4]
save_config({"color_table": tbl2})
ok(codes.color_hex(load_config())["随机颜色"]["hex"] == codes.NEUTRAL_HEX, "empty = default neutral grey")
# 老数据（没有第 5 列的默认表）也有效
save_config({"color_table": [list(r) for r in codes.DEFAULT_COLORS]})
ok(codes.color_hex(load_config())["随机颜色"]["hex"] == codes.NEUTRAL_HEX, "default table valid")

# ---------- 2. 最常用颜色（角标小圆点） ----------
cfg = load_config()
pop = codes.popular_colors(cfg, 6, [{"variants": [{"opt1_zh": "蓝色"}, {"opt1_zh": "蓝色"}, {"opt1_zh": "绿色"}]}, {"variants": [{"opt1_zh": "蓝色"}, {"opt1_zh": "随机颜色"}]}])
ok(pop[0]["zh"] == "蓝色" and pop[1]["zh"] == "绿色" and len(pop) == 6, f"most-used first {[x['zh'] for x in pop]}")
ok(not any(x["zh"] in ("随机颜色", "多色", "彩虹渐变", "透明") for x in pop), "no random / multi / rainbow / clear dots")
ok(len(codes.popular_colors(cfg, 3, [])) == 3, "no data → table order")

# ---------- 3. 角标 ----------
base = Image.new("RGB", (600, 600), (250, 250, 250))
dots = [x["hex"] for x in pop[:5]]
for lang in ("thai", "chinese", "bilingual"):
    im = colorbadge.draw_badge(base, dots, lang)
    diff = ImageChops.difference(base, im).getbbox()
    ok(diff is not None and diff[0] > 300 and diff[1] > 500 and diff[2] <= 600 and diff[3] <= 600, f"badge ({lang}) drawn bottom-right only {diff}")
ok(colorbadge.draw_badge(base, dots, "chinese").tobytes() != colorbadge.draw_badge(base, dots, "thai").tobytes(), "badge text follows the language")
ok(colorbadge.apply(base, {"random_badge": False})[1] is False and colorbadge.apply(base, {"random_badge": False})[0].tobytes() == base.tobytes(), "disabled in settings → untouched")
ok(colorbadge.apply(base, {"random_badge": True, **cfg})[1] is True, "enabled → badge")
ok(colorbadge.apply(base, {"random_badge": False}, enabled=True)[1] is True, "explicit override on")

# ---------- 4. 生成商品图接口 ----------
import base64
def png(color=(210, 206, 198)):
    bio = io.BytesIO(); Image.new("RGB", (800, 800), color).save(bio, "PNG"); return "data:image/png;base64," + base64.b64encode(bio.getvalue()).decode()
PID = "3DP0002"
p = store.load(PID)
p["variants"] = [{"opt1_zh": "红色", "opt2_zh": "", "sku": "3DP0002-RD", "grams": 30, "hours": 1}, {"opt1_zh": "随机颜色", "opt2_zh": "", "sku": "3DP0002-RND", "grams": 30, "hours": 1}]
p["images"] = []; store.save(p)
def saved(pid, entry):
    return Image.open(os.path.join(store.image_dir(pid, "out"), entry["file"])).convert("RGB")
def corner(im):
    w, h = im.size; return im.crop((int(w * 0.5), int(h * 0.88), w, h))
def flat(im):
    return len(set(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())) <= 3
save_config({"random_badge": True})
r = C.post(f"/api/products/{PID}/images/rendered", json={"images": [{"data": png(), "kind": "main", "color": "随机颜色", "random": True}, {"data": png(), "kind": "main", "color": "红色"}]}).get_json()
imgs = {i["color"]: i for i in r["product"]["images"]}
rnd, red = saved(PID, imgs["随机颜色"]), saved(PID, imgs["红色"])
ok(not flat(corner(rnd)) and flat(corner(red)), "random-colour image has the badge, a real colour has none")
ok(next(v for v in r["product"]["variants"] if v["opt1_zh"] == "随机颜色")["image"] == imgs["随机颜色"]["file"], "variant image set")
r = C.post(f"/api/products/{PID}/images/rendered", json={"random_badge": False, "images": [{"data": png(), "kind": "main", "color": "随机颜色", "random": True}]}).get_json()
ok(flat(corner(saved(PID, r["product"]["images"][-1]))), "request random_badge=false → no badge")
save_config({"random_badge": False})
r = C.post(f"/api/products/{PID}/images/rendered", json={"images": [{"data": png(), "kind": "main", "color": "随机颜色", "random": True}]}).get_json()
ok(flat(corner(saved(PID, r["product"]["images"][-1]))), "settings random_badge off → no badge")
r = C.post(f"/api/products/{PID}/images/rendered", json={"random_badge": True, "images": [{"data": png(), "kind": "main", "color": "随机颜色", "random": True}]}).get_json()
ok(not flat(corner(saved(PID, r["product"]["images"][-1]))), "request random_badge=true wins over settings")
save_config({"random_badge": True})
ok(load_config()["random_badge"] is True and load_config()["random_badge_lang"] == "thai", "defaults: badge on, Thai text")

# ---------- 5. 识别参考图用同一个中性灰 ----------
from modules.recog import refs, render
ok(render.hex_rgb(codes.NEUTRAL_HEX) == (207, 203, 196), "recog fallback grey = neutral")
ok(refs._color_rgb(load_config(), "随机颜色") == (None, None) and refs._color_rgb(load_config(), "红色")[0] == "RD", "recog still treats random as unreliable colour")

# ---------- 6. 尺寸显示 ----------
ok(fmtnum.size_text([52.18000030517578, 64.88999938964844, 18]) == "52.2 × 64.9 × 18 mm", fmtnum.size_text([52.18000030517578, 64.88999938964844, 18]))
ok(fmtnum.num(18.0) == "18" and fmtnum.num(0.04) == "0" and fmtnum.num(-0.01) == "0" and fmtnum.num(2.25) in ("2.2", "2.3") and fmtnum.num("x") == "" and fmtnum.num(None) == "", "num edge cases")
ok(fmtnum.size_text([1, None, 3]) == "" and fmtnum.size_text([]) == "", "bad input → empty")
ok(fmtnum.cm_from_mm(52.18000030517578) == 5.2, "cm_from_mm")
js = open(os.path.join(APP, "static", "ux.js"), encoding="utf-8").read()
ok("function num(" in js and "sizeText" in js, "UX.num / UX.sizeText exist")
import subprocess, shutil as _sh
if _sh.which("node"):
    code = ("const w={};global.window=w;global.document={addEventListener(){}};" + js + ";"
            "const U=w.UX;console.log(JSON.stringify([U.num(52.18000030517578),U.num(18),U.num(18.04),U.num(null),U.sizeText([52.18000030517578,64.88999938964844,18]),U.sizeText([1,'x',3]),U.sizeText({x:1.25,y:2,z:3},'×')]))")
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True).stdout.strip()
    ok(out == '["52.2","18","18","","52.2 × 64.9 × 18 mm","","1.3×2×3 mm"]', f"JS UX.num / sizeText {out}")
mj = open(os.path.join(APP, "modules", "model", "ui", "model.js"), encoding="utf-8").read()
ok("UX.sizeText(s)" in mj and "${s[0]} ×" not in mj, "editor model info uses the formatter")

print("ERRORS", E_)
sys.exit(1 if E_ else 0)
