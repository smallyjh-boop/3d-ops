# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys
os.environ["LH_DATA_DIR"]=T+"/opsdata"; sys.path.insert(0,APP)
import app as A
from core import db, integrations
try: db.create_user("boss","secret1","owner","boss","zh")
except Exception: pass
c=A.app.test_client(); c.post("/api/auth/login",json={"username":"boss","password":"secret1"})
rk=c.post("/api/apikeys", json={"name":"分析系统","scope":"read"}).get_json()["key"]
fk=c.post("/api/apikeys", json={"name":"推送","scope":"full"}).get_json()["key"]
print([ (k["name"],k["scope"]) for k in integrations.list_keys()])
x=A.app.test_client()
H=lambda k: {"Authorization":"Bearer "+k}
for path in ["/api/v1/ping","/api/v1/skus","/api/v1/cost-params","/api/v1/profit?days=7","/api/v1/orders","/api/v1/production"]:
    r=x.get(path, headers=H(rk)); j=r.get_json(); print(path, r.status_code, j.get("ok"), j.get("count"), (j.get("error") or "")[:60])

print("post with read", x.post("/api/v1/orders", json={}, headers=H(rk)).status_code, x.get("/api/v1/cs/ping", headers=H(rk)).status_code)
print("cs with full", x.get("/api/v1/cs/ping", headers=H(fk)).status_code)
o=x.get("/api/v1/orders?limit=3", headers=H(rk)).get_json()["orders"]; print("read order keys has buyer/phone:", any(k in o[0] for k in ("buyer","phone","address")), "cost" in o[0], o[0]["cost"].get("profit") if isinstance(o[0]["cost"],dict) else None)
o=x.get("/api/v1/orders?limit=3", headers=H(fk)).get_json()["orders"]; print("full order has buyer:", "buyer" in o[0])
