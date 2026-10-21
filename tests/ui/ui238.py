# v2.38 界面：上架客服（没有金额权限）打开库存、物品详情、采购单列表和详情——不显示金额、没有 JS 报错；
# 老板看得到金额；订单「修改订单」只改备注金额不变
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import asyncio, json, sys
from playwright.async_api import async_playwright
B = "http://127.0.0.1:8799"; ERR = []
JS = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "th_missing.js"), encoding="utf-8").read()
LANG = sys.argv[1] if len(sys.argv) > 1 else "zh"
async def login(b, u, p):
    c = await b.new_context(viewport={"width": 1400, "height": 900}); pg = await c.new_page()
    pg.on("pageerror", lambda e: (ERR.append(f"{u}: {e}"), print("  pageerror:", u, (e.stack or "")[:300])))
    pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await pg.goto(B + "/login"); await pg.fill("#username", u); await pg.fill("#password", p); await pg.click("#btn"); await pg.wait_for_timeout(1500)
    await pg.evaluate(f"localStorage.setItem('ui_lang','{LANG}')"); await pg.reload(); await pg.wait_for_timeout(3000)
    return pg
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); miss = set()
        boss = await login(b, "boss", "secret1")
        d = await boss.evaluate("""(async()=>{
            const it=(await api('/api/inv/items',{json:{name_zh:'UI238胶带',category:'pack',unit:'卷'}})).item;
            const s=await api('/api/inv/suppliers',{json:{name:'UI238供应商'}}); const sid=(s.supplier||s).id;
            const po=(await api('/api/inv/po',{json:{supplier_id:sid,lines:[{item_id:it.id,qty:10,unit_cost:5}]}})).po;
            await api('/api/inv/po/'+po.id+'/order',{json:{}});
            await api('/api/inv/po/'+po.id+'/receive',{json:{qtys:{[po.lines[0].id]:4}}});
            return {iid:it.id, code:it.code, po:po.id}})()""")
        # 老板：库存页有金额
        await boss.evaluate("goTab('inventory')"); await boss.wait_for_timeout(1500)
        own = await boss.evaluate("document.querySelector('#tab-inventory').innerText")
        if "฿" not in own: ERR.append("v238 owner should see money on inventory page")
        nok = await login(b, "nok", "pass123")
        await nok.evaluate("goTab('inventory')"); await nok.wait_for_timeout(1500)
        txt = await nok.evaluate("document.querySelector('#tab-inventory').innerText")
        if "฿" in txt: ERR.append("v238 listing sees money on inventory page")
        exp = await nok.evaluate("""[...document.querySelectorAll('#inv-views [data-iv="expense"]')].every(x=>x.classList.contains('hidden'))""")
        if not exp: ERR.append("v238 expense tab visible for listing")
        if LANG == "th": miss.update(await nok.evaluate(JS, "#tab-inventory"))
        row = await nok.query_selector(f"text={d['code']}")
        if row:
            await row.click(); await nok.wait_for_timeout(1000)
            mt = await nok.evaluate("(document.querySelector('#modal-in')||{}).innerText||''")
            if "฿" in mt: ERR.append("v238 item detail shows money to listing")
            await nok.evaluate("MODAL.close && MODAL.close()")
        await nok.evaluate("goTab('purchase')"); await nok.wait_for_timeout(1500)
        pt = await nok.evaluate("(document.querySelector('#tab-purchase')||document.body).innerText")
        if "฿" in pt: ERR.append("v238 purchase list shows money to listing")
        btn = await nok.query_selector(f"[data-po='{d['po']}']")
        if btn:
            await btn.click(); await nok.wait_for_timeout(1000)
            mt = await nok.evaluate("(document.querySelector('#modal-in')||{}).innerText||''")
            if "฿" in mt: ERR.append("v238 PO detail shows money to listing")
            if LANG == "th": miss.update(await nok.evaluate(JS, "#modal-in"))
        else:
            ERR.append("v238 PO not listed for listing user")
        print(" v238 listing inv/purchase checked")
        json.dump(sorted(miss), open(_os.path.join(T, "miss238.json"), "w", encoding="utf-8"), ensure_ascii=False)
        await b.close()
    print("ERR", ERR)
    sys.exit(1 if ERR else 0)
asyncio.run(main())
