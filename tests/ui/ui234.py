# v2.34 界面：库存 → 货位按「区+货架号-层-位」（新建货架、加一层、货架设置、扫物品找货位）；
# 设置 → 订单与售后 →「平台面单：自定义加信息」（来源一览、模板、实时预览）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import asyncio, json, sys
from playwright.async_api import async_playwright
B="http://127.0.0.1:8799"; SP=T; ERR=[]
JS=open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),"th_missing.js"),encoding="utf-8").read()
LANG=sys.argv[1] if len(sys.argv)>1 else "zh"
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); miss=set()
        c=await b.new_context(viewport={"width":1400,"height":900}); pg=await c.new_page()
        pg.on("pageerror", lambda e: ERR.append(str(e))); pg.on("console", lambda m: ERR.append(m.text) if m.type=="error" and "404" not in m.text and "400" not in m.text else None)
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(B+"/login"); await pg.fill("#username","boss"); await pg.fill("#password","secret1"); await pg.click("#btn"); await pg.wait_for_timeout(1500)
        await pg.evaluate(f"localStorage.setItem('ui_lang','{LANG}')"); await pg.reload(); await pg.wait_for_timeout(3500)
        await pg.evaluate("goTab('inventory')"); await pg.wait_for_timeout(1500)
        await pg.click("#inv-views [data-iv=locations]"); await pg.wait_for_timeout(1200)
        shelf = "Y1" if LANG == "zh" else "Y2"
        await pg.click("#loc-bulk"); await pg.wait_for_timeout(500)
        await pg.fill("#lb-zone", "Y"); await pg.fill("#lb-shelf", shelf[1:]); await pg.fill("#lb-layers", "3"); await pg.fill("#lb-pos", "4")
        await pg.fill("#lb-name", "Test rack"); await pg.click(".loc-catbox input[value=pack]")
        prev = await pg.evaluate("document.querySelector('#lb-prev').textContent")
        if f"{shelf}-03-04" not in prev: ERR.append("v234 preview text " + prev)
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#modal-in"))
        await pg.click("#lb-ok"); await pg.wait_for_timeout(1500)
        n = await pg.evaluate(f"document.querySelectorAll('.loc-shelf[data-shelf={shelf}] .loc-cell').length")
        print(" v234 cells:", n)
        if n != 12: ERR.append("v234 shelf cells")
        await pg.click(f"[data-addlayer={shelf}]"); await pg.wait_for_timeout(1200)
        n = await pg.evaluate(f"document.querySelectorAll('.loc-shelf[data-shelf={shelf}] .loc-cell').length")
        if n != 16: ERR.append(f"v234 add layer {n}")
        await pg.click(f"[data-grp={shelf}]"); await pg.wait_for_timeout(500)
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#modal-in"))
        await pg.click("#lg-ok"); await pg.wait_for_timeout(1000)
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-inventory"))
        await pg.screenshot(path=SP+f"/v234_loc_{LANG}.png", full_page=True)
        await pg.fill("#loc-scan", shelf); await pg.press("#loc-scan", "Enter"); await pg.wait_for_timeout(800)
        if not await pg.evaluate("!!document.querySelector('.loc-shelf.loc-hl')"): ERR.append("v234 scan shelf highlight")
        # 设置 → 订单与售后：平台面单卡片
        await pg.evaluate("CFG_MOD='orders'; goTab('settings')"); await pg.wait_for_timeout(2500)
        ok = await pg.evaluate("!!document.querySelector('#wb-card') && document.querySelectorAll('#wb-card .wb-src tbody tr').length >= 4")
        print(" v234 waybill card:", ok)
        if not ok: ERR.append("v234 waybill card")
        await pg.fill("#wb-info", "40"); await pg.wait_for_timeout(1500)
        src = await pg.evaluate("document.querySelector('#wb-fr').src")
        if "info_mm%22%3A40" not in src: ERR.append("v234 live preview " + src[:120])
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-settings"))
        await pg.screenshot(path=SP+f"/v234_waybill_{LANG}.png", full_page=True)
        miss={m for m in miss if not any(x in m for x in ("粉色","荧光绿"))}
        open(SP+"/miss234.json","w").write(json.dumps(sorted(miss),ensure_ascii=False,indent=0)); print("MISS",len(miss)); print("ERR",ERR[:8])
asyncio.run(main())
