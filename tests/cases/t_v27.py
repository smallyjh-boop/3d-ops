# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, io, time, json, zipfile
os.environ["LH_DATA_DIR"]=T+"/v27"; sys.path.insert(0,APP)
import app as A
from core import db, config
from core.cs import data as csd, presets
for u,r in (("boss","owner"),("som","production"),("nok","listing")):
    try: db.create_user(u,"pass123" if u!="boss" else "secret1",r,u,"th")
    except Exception: pass
def cl(u,pw):
    c=A.app.test_client(); c.post("/api/auth/login",json={"username":u,"password":pw}); return c
boss=cl("boss","secret1"); nok=cl("nok","pass123"); som=cl("som","pass123")
print("ship days", config.load_config()["default_ship_days"])
# presets update: insert old text then run update
c=db.conn(); p=[x for x in presets.PRESETS if x.get("old")][0]
c.execute("UPDATE cs_kb SET a=? WHERE q=?", (p["old"][0], p["q"])); c.commit()
print("updated", csd.update_presets(), "missing", csd.presets_missing(), "kb", c.execute("select count(*) from cs_kb").fetchone()[0])
print("policy", csd.settings()["ship_policy"][:30])
# system check
r=boss.get("/api/system/check"); j=r.get_json(); print("check", r.status_code, j["summary"]); 
for it in j["items"]: print("  ", it["status"], it["group"], it["name"], "|", it["detail"][:70])
print("nok check", nok.get("/api/system/check").status_code)
# backup verify
r=boss.post("/api/backups", json={}); name=r.get_json()["name"]
print("verify", boss.post(f"/api/backups/{name}/verify", json={}).get_json())
# user tabs
uid=[u for u in boss.get("/api/users").get_json()["users"] if u["username"]=="nok"][0]["id"]
r=boss.post(f"/api/users/{uid}", json={"tabs":["cs","cskb","library"]}); print("tabs", r.get_json()["user"]["tabs"])
print("nok me tabs", nok.get("/api/me").get_json()["user"]["tabs"])
boss.post(f"/api/users/{uid}", json={"tabs":[]}); print("cleared", nok.get("/api/me").get_json()["user"]["tabs"])
# overdue / perf
cv=csd.create_conv(buyer="b1", platform="lazada")
csd.add_msg(cv["id"],"buyer","สวัสดีค่ะ", ts=time.time()-1200)
csd.add_msg(cv["id"],"seller","ok", ai_draft="ok", ts=time.time()-1100)
csd.add_msg(cv["id"],"buyer","ส่งกี่วัน", ts=time.time()-900)
print("overdue", [(x["buyer"],x["wait_min"]) for x in csd.overdue()])
print("perf", boss.get("/api/cs/perf").get_json()["perf"])
print("stats", nok.get("/api/cs/stats").get_json())
print("convs wait", [(x["buyer"], x["wait_min"]) for x in nok.get("/api/cs/convs").get_json()["convs"]], nok.get("/api/cs/convs").get_json()["alert_minutes"])
# telegram mocked
from core.cs import alerts
class R:
    headers={"content-type":"application/json"}
    def __init__(s,j): s._j=j
    def json(s): return s._j
sent=[]
alerts.requests.post=lambda url, json=None, timeout=None: (sent.append(json), R({"ok":True}))[1]
alerts.requests.get=lambda url, timeout=None: R({"ok":True,"result":[{"message":{"chat":{"id":12345,"first_name":"King"}}}]})
csd.save_settings({"tg_token":"1:a","tg_chat":"12345"})
print("alert n", alerts.check_once(), "again", alerts.check_once(), sent[-1]["text"][:60])
print("chat id", boss.post("/api/cs/alert/chat-id", json={"tg_token":"1:a"}).get_json())
print("test", boss.post("/api/cs/alert/test", json={}).get_json())
