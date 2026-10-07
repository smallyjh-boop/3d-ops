import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, json
os.environ["LH_DATA_DIR"]=T+"/v20"; os.environ["PORT"]="8799"; sys.argv.append("--no-browser")
sys.path.insert(0,APP)
import app as A
from core import ai_copy, db
def fake(cfg, system, user, image_b64=None):
    if image_b64:
        return json.dumps({"platform":"lazada","buyer":"Somchai","order_no":"","messages":[{"from":"buyer","text":"สวัสดีค่ะ แมวสีชมพูมีไหมคะ"}]})
    if "空打" in system:
        return json.dumps({"overall":{"level":"中","zh":"桌腿细高，容易被撞倒","th":"ขาโต๊ะสูงบาง อาจล้มได้"},
          "items":[{"name":"桌腿","level":"中","risk_zh":"细高","fix_zh":"加帽檐、降速","risk_th":"สูงบาง","fix_th":"เพิ่ม brim","suggest_orient":"front"}],
          "settings_zh":"树状支撑 + 5mm 帽檐","settings_th":"ซัพพอร์ตแบบต้นไม้ + brim 5mm"})
    if "翻译" in system: return '{"text":"（翻译）"}'
    if "selling-point text for e-commerce product images" in system:
        return json.dumps({"headline_th":"โคมไฟแมวน่ารัก","headline_zh":"可爱猫咪灯","sub_th":"แต่งห้องให้อบอุ่น","sub_zh":"让房间更温馨",
          "badge_th":["ขายดี","ใหม่"],"points":[{"th":"ขนาด 12 × 10 ซม.","zh":"尺寸","icon":"ruler"},{"th":"มีให้เลือก 5 สี","zh":"5色","icon":"palette"},
          {"th":"ของขวัญวันเกิด","zh":"生日礼物","icon":"gift"},{"th":"ใส่ชื่อได้","zh":"可刻名","icon":"heart"},{"th":"พิมพ์ 3D ทุกชิ้น","zh":"x","icon":"check"},{"th":"ส่งไวใน 48 ชม.","zh":"48h","icon":"truck"}]})
    ctx=json.loads(user.split("\n\n输出")[0])
    pend=ctx.get("待回复的买家消息") or []
    q=ctx.get("批发报价（程序算好的）")
    wh=any("30" in p for p in pend)
    return json.dumps({"lang":"th","buyer_msgs_zh":["(中)"+p[:20] for p in pend],"intent":"wholesale" if wh else "product",
      "summary_zh":"买家询问："+(pend[-1][:30] if pend else ""),
      "reply":"สวัสดีค่ะคุณลูกค้า มีสีชมพูพร้อมส่งค่ะ" + (" 30 ตัว ตัวละ %s บาท"%q["lines"][0]["unit_price"] if (wh and q) else ""),
      "reply_zh":"您好，有粉色现货","needs_human":False,"confidence":0.9,"order_no":"","custom_request_zh":"","custom_request_th":"",
      "order_note_zh":"","wholesale_items":[{"sku":"3DP0001-PK","qty":30}] if wh else [],"kb_ids_used":[],"save_as_faq":False})
ai_copy.call=fake
try: db.create_user('boss','secret1','owner','老板','zh'); db.create_user('nok','pass123','listing','Nok','th')
except Exception: pass
db.release()
A.main()
