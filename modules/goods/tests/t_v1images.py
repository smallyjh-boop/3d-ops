# v2.32.1：接口需求单「skus 接口加商品主图 + 只读图片下载接口」的联调步骤
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, time
D = T + "/m_v1img"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import store, integrations
from PIL import Image
C = A.app.test_client()
H = {"Authorization": "Bearer " + integrations.create_key("分析系统-只读", "read")}
# 准备：一个产品放两张图（大图 1200px），第二个变体选第 2 张图
pid = store.list_products()[0]["id"]
p = store.load(pid)
def mk(name, color, size=(1200, 900)):
    d = store.image_dir(pid, "out"); Image.new("RGB", size, color).save(os.path.join(d, name), "JPEG")
    return {"file": name, "raw": name, "processed": True}
p["images"] = [mk("cov.jpg", "red"), mk("blue.jpg", "blue")]
vs = p["variants"]
if len(vs) < 2:
    vs.append(dict(vs[0], sku=vs[0]["sku"] + "X", opt1_zh="蓝色"))
vs[1]["image"] = "blue.jpg"
store.save(p)
# 1. skus 每条有 image
r = C.get("/api/v1/skus?since=0", headers=H).get_json()
mine = [x for x in r["skus"] if x["product_id"] == pid]
ok(all("image" in x for x in r["skus"]), "every sku has image field")
ok(mine[0]["image"]["for"] == "product" and mine[1]["image"]["for"] == "sku" and mine[0]["image"]["id"] != mine[1]["image"]["id"], f"sku own image vs cover {[x['image'] for x in mine[:2]]}")
ok(mine[0]["image"]["url"] == "/api/v1/images/" + mine[0]["image"]["id"] and mine[0]["image"]["updated_at"] > 0, "url / updated_at")
noimg = [x for x in r["skus"] if not (store.load(x["product_id"]).get("images"))]
ok(all(x["image"] is None for x in noimg), f"no image -> null ({len(noimg)})")
# 2. 下载小图 / 原图，ETag 304
url = mine[0]["image"]["url"]
t = C.get(url + "?size=thumb", headers=H)
im = Image.open(io.BytesIO(t.data))
ok(t.status_code == 200 and t.mimetype == "image/jpeg" and max(im.size) <= 400, f"thumb {im.size}")
o = C.get(url, headers=H); ok(max(Image.open(io.BytesIO(o.data)).size) == 1200, "original")
et = t.headers.get("ETag")
ok(et and C.get(url + "?size=thumb", headers={**H, "If-None-Match": et}).status_code == 304, "304 with ETag")
ok(t.headers.get("Last-Modified"), "Last-Modified")
# 3. 换封面 → since 拉到、编号变
before = mine[0]["image"]["id"]; t0 = time.time() - 1
time.sleep(1.1)
p = store.load(pid); p["images"] = list(reversed(p["images"])); store.save(p)
r2 = C.get(f"/api/v1/skus?since={int(t0)}", headers=H).get_json()
m2 = [x for x in r2["skus"] if x["product_id"] == pid]
ok(m2 and m2[0]["image"]["id"] != before, "cover change -> new id via since")
# 4. 不存在 / 拼路径 / 别的文件 → 404
for bad in ("NOPE-0123456789", f"{pid}-0123456789", "..%2F..%2Fconfig.json", "../app.db", f"{pid}-../../x", "%2e%2e%2fapp.db"):
    rr = C.get("/api/v1/images/" + bad, headers=H)
    ok(rr.status_code == 404 and (rr.get_json(silent=True) or {}).get("code") == "not_found", f"404 for {bad} ({rr.status_code})")
# 权限：没有密钥不行；只读密钥只能 GET
ok(C.get(url).status_code == 401, "needs key")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
