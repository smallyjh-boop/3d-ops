# v2.33 界面：库存 → 货位（批量建、点开货位、未上架一键上架）；设置 → 订单与售后 → 面单模板预览
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
        if not await pg.evaluate("!!document.querySelector('.loc-cell')"):
            await pg.click("#loc-bulk"); await pg.wait_for_timeout(500)
            await pg.fill("#lb-zone", "Z"); await pg.fill("#lb-sh", "2"); await pg.fill("#lb-c", "3")
            await pg.click("#lb-ok"); await pg.wait_for_timeout(1500)
        n = await pg.evaluate("document.querySelectorAll('.loc-cell').length")
        print(" v233 cells:", n)
        if n < 6: ERR.append("v233 bulk")
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-inventory"))
        await pg.screenshot(path=SP+f"/v233_loc_{LANG}.png", full_page=True)
        if await pg.evaluate("!!document.querySelector('#loc-unplaced')"):
            await pg.click("#loc-unplaced"); await pg.wait_for_timeout(1000)
            if LANG=="th": miss|=set(await pg.evaluate(JS,"#modal-in"))
            await pg.click("#loc-all"); await pg.wait_for_timeout(1500)
        await pg.click(".loc-cell.on, .loc-cell"); await pg.wait_for_timeout(1000)
        md = await pg.evaluate("document.querySelector('#modal-in').innerText")
        print(" v233 detail:", md[:80].replace("\n"," | "))
        if "货位" not in md and "ตำแหน่ง" not in md and "ช่องเก็บ" not in md: ERR.append("v233 detail")
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#modal-in"))
        await pg.evaluate("MODAL.close()")
        await pg.fill("#loc-scan", "Z-01-01"); await pg.press("#loc-scan", "Enter"); await pg.wait_for_timeout(1000)
        if not await pg.evaluate("!document.querySelector('#modal').classList.contains('hidden')"): ERR.append("v233 scan")
        await pg.evaluate("MODAL.close()")
        # 面单模板预览
        await pg.evaluate("CFG_MOD='orders'; goTab('settings')"); await pg.wait_for_timeout(2500)
        fr = await pg.evaluate("document.querySelectorAll('#lt-grid iframe').length")
        print(" v233 label previews:", fr)
        if fr < 9: ERR.append("v233 label preview")
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-settings"))
        await pg.screenshot(path=SP+f"/v233_labels_{LANG}.png", full_page=True)
        miss={m for m in miss if not any(x in m for x in ("粉色","荧光绿"))}
        open(SP+"/miss233.json","w").write(json.dumps(sorted(miss),ensure_ascii=False,indent=0)); print("MISS",len(miss)); print("ERR",ERR[:8])
asyncio.run(main())
