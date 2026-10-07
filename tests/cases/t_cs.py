# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, json
SP=T+""
os.environ["LH_DATA_DIR"]=T+"/v20"; sys.path.insert(0,APP)
import app as A
from core import ai_copy, db
CALLS=[]
def fake(cfg, system, user, image_b64=None):
    CALLS.append((system[:30], len(user), bool(image_b64)))
    if image_b64:
        return json.dumps({"platform":"shopee","buyer":"somchai_88","order_no":"","messages":[{"from":"buyer","text":"สวัสดีค่ะ แมวสีชมพูมีไหมคะ"},{"from":"seller","text":"มีค่ะ"},{"from":"buyer","text":"ถ้าซื้อ 30 ตัว ลดได้ไหมคะ ส่งกี่วัน"}]})
    if "翻译" in system: return '{"text":"翻译"}'
    ctx=json.loads(user.split("\n\n输出")[0])
    q=ctx.get("批发报价（程序算好的）")
    return json.dumps({"lang":"th","buyer_msgs_zh":["你好 有粉色猫吗","买30个能便宜吗 几天发货"],"intent":"wholesale","summary_zh":"询问30个粉色猫批发价",
      "reply":"ได้ค่ะ 30 ตัว ราคาตัวละ %s บาท ส่งภายใน %s วันค่ะ"%((q or {}).get("lines",[{}])[0].get("unit_price"),(q or {}).get("ship_days")),
      "reply_zh":"可以","needs_human":False,"confidence":0.9,"order_no":"","custom_request_zh":"刻名字 Somchai","custom_request_th":"สลักชื่อ Somchai",
      "order_note_zh":"","wholesale_items":[{"sku":"3DP0001-PK","qty":30}],"kb_ids_used":[],"save_as_faq":False})
ai_copy.call=fake
try: db.create_user("boss","secret1","owner","老板","zh")
except Exception: pass
c=A.app.test_client()
c.post("/api/auth/login",json={"username":"boss","password":"secret1"})
def J(r):
    d=r.get_json()
    if r.status_code>=400: print("  ERR",r.status_code,d)
    return d
# 1 manual conversation
cv=J(c.post("/api/cs/convs",json={"buyer":"nok","platform":"lazada","text":"สวัสดีค่ะ อยากสั่งแมว 30 ตัว ราคาส่งเท่าไหร่คะ"}))
cid=cv["id"]; print("conv",cid,len(cv["messages"]),cv["order_candidates"])
d=J(c.post(f"/api/cs/convs/{cid}/draft",json={}))
print("draft:",d["draft"],"| intent",d["intent"],"| sugg",[s["type"]+":"+s["label"] for s in d["suggestions"]])
print("quote",d["analysis"]["quote"]["lines"], d["analysis"]["quote"]["ship_days"])
# action quote
qa=[s for s in d["suggestions"] if s["type"]=="quote"][0]
r=J(c.post(f"/api/cs/convs/{cid}/action",json=qa)); print("action:",r["message"], r["order"]["order_no"], r["order"]["status"])
r=J(c.post(f"/api/cs/convs/{cid}/action",json={"type":"custom_note","text":"刻名字 Somchai｜สลักชื่อ Somchai"})); print(r["message"], r["order"]["custom_note"])
r=J(c.post(f"/api/cs/convs/{cid}/sent",json={"text":"ได้ค่ะ ตัวละ 80 บาทค่ะ"})); print("status after sent",r["status"], len(r["messages"]))
print("examples", len(J(c.get("/api/cs/kb"))["examples"]))
# 2 extension capture with API key
k=J(c.post("/api/apikeys",json={"name":"ext-nok"})); key=k.get("key") or k.get("raw") or k
print("key resp keys", list(k.keys()) if isinstance(k,dict) else k)
key=k["key"]
H={"Authorization":"Bearer "+key}
r=J(c.post("/api/v1/cs/capture",headers=H,json={"url":"https://sellercenter.lazada.co.th/apps/im/chat","shop":"MyShop","buyer":"pim",
   "messages":[{"from":"buyer","text":"สวัสดีค่ะ"},{"from":"buyer","text":"สั่งไปเมื่อวาน 26100512345 ส่งยังคะ"}]}))
print("cap1", r["id"], r["platform"], r.get("added"), r["draft"][:40] if r.get("draft") else None, r.get("order") and r["order"]["order_no"])
r2=J(c.post("/api/v1/cs/capture",headers=H,json={"url":"https://sellercenter.lazada.co.th/apps/im/chat","shop":"MyShop","buyer":"pim",
   "messages":[{"from":"buyer","text":"สวัสดีค่ะ"},{"from":"buyer","text":"สั่งไปเมื่อวาน 26100512345 ส่งยังคะ"}]}))
print("cap2 same id", r2["id"]==r["id"], "added", r2["added"], "calls", len(CALLS))
r3=J(c.post("/api/v1/cs/capture",headers=H,json={"url":"https://seller.shopee.co.th/webchat","shop":"S1","screenshot":"data:image/png;base64,"+__import__("base64").b64encode(open(SP+"/y_live_none_zh.png","rb").read()).decode()}))
print("shot", r3["platform"], r3["buyer"], r3["added"], len(r3["messages"]))
r4=J(c.post("/api/v1/cs/sent",headers=H,json={"conv_id":r["id"],"text":"ส่งแล้วค่ะ"})); print("sent", r4["status"])
print(c.options("/api/v1/cs/capture",headers={"Origin":"chrome-extension://abc"}).status_code)
print(c.get("/api/v1/cs/ping",headers=H).get_json())
