# v2.32 界面：打包核对（点一下确认 / 扫码）、库存页分「库存 / 物品资料」、财务订单明细、切片文件机型
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
        # 打包核对：建一个手工单，默认「点一下确认」
        o = await pg.evaluate("""(async()=>{const l=await api('/api/products');const p=await api('/api/products/'+l[0].id);
            await api('/api/config',{json:{review_enabled:false,scan_order_key:'both',pack_item_mode:'tap'}});
            return await api('/api/orders/manual',{json:{order_no:'UI232-'+Date.now(),order_total:99,items:[{sku:p.variants[0].sku,qty:2}]}})})()""")
        await pg.evaluate("goTab('pack')"); await pg.wait_for_timeout(800)
        await pg.fill("#pk-code", o["order_no"]); await pg.press("#pk-code", "Enter"); await pg.wait_for_timeout(1200)
        st = await pg.evaluate("[!!document.querySelector('[data-pktap]'), document.querySelector('#pk-done').disabled, !!document.querySelector('a[href^=\"/print/item-labels\"]')]")
        await pg.click("[data-pktap]"); await pg.wait_for_timeout(300)
        en = await pg.evaluate("!document.querySelector('#pk-done').disabled")
        print(" v232 pack tap:", st, en)
        if not (st[0] and st[1] and st[2] and en): ERR.append("v232 pack tap")
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-pack"))
        await pg.screenshot(path=SP+f"/v232_pack_{LANG}.png", full_page=True)
        # 库存：库存 / 物品资料
        await pg.evaluate("goTab('inventory')"); await pg.wait_for_timeout(1500)
        await pg.click("#inv-views [data-iv=catalog]"); await pg.wait_for_timeout(1200)
        cat = await pg.evaluate("[!!document.querySelector('#inv-sub'), document.querySelectorAll('#inv-body tbody tr').length]")
        await pg.select_option("#inv-sub", "zero"); await pg.wait_for_timeout(1000)
        print(" v232 inventory catalog:", cat)
        if not cat[0]: ERR.append("v232 inv catalog")
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-inventory"))
        await pg.click("#inv-views [data-iv=items]"); await pg.wait_for_timeout(1000)
        await pg.screenshot(path=SP+f"/v232_inv_{LANG}.png", full_page=True)
        # 财务：订单明细
        await pg.evaluate("goTab('fin_orders')"); await pg.wait_for_timeout(2000)
        fo = await pg.evaluate("[document.querySelectorAll('#fin-od tbody tr').length, !!document.querySelector('a[href^=\"/api/fin/orders/export\"]')]")
        print(" v232 fin orders:", fo)
        if not fo[1]: ERR.append("v232 fin orders")
        if await pg.evaluate("!!document.querySelector('[data-odrow]')"):
            await pg.click("[data-odrow]"); await pg.wait_for_timeout(600)
            md = await pg.evaluate("document.querySelector('#modal-in').innerText.length")
            if md < 50: ERR.append("v232 fin detail")
            if LANG=="th": miss|=set(await pg.evaluate(JS,"#modal-in"))
            await pg.evaluate("MODAL.close()")
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-fin_orders"))
        await pg.screenshot(path=SP+f"/v232_fin_{LANG}.png", full_page=True)
        # 设置 → 订单与售后：扫码设置；生产 → 打印机：喷嘴 / 热床板
        await pg.evaluate("CFG_MOD='orders'; goTab('settings')"); await pg.wait_for_timeout(1500)
        s1 = await pg.evaluate("!!document.querySelector('[data-c=scan_order_key]')")
        await pg.evaluate("CFG_MOD='production'; goTab('settings')"); await pg.wait_for_timeout(1500)
        s2 = await pg.evaluate("!!document.querySelector('#printer-table [data-p=nozzle]')")
        print(" v232 settings:", s1, s2)
        if not (s1 and s2): ERR.append("v232 settings")
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-settings"))
        miss={m for m in miss if not any(x in m for x in ("粉色","荧光绿"))}
        open(SP+"/miss232.json","w").write(json.dumps(sorted(miss),ensure_ascii=False,indent=0)); print("MISS",len(miss)); print("ERR",ERR[:8])
asyncio.run(main())
