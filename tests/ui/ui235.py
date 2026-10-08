# v2.35 界面：货位一物一位（批量建货架、点格子放物品、没货位的物品、按货架盘点）、库存「纸箱」统计、
# 产品选邮政纸箱、订单详情「发货出库」（纸箱 + 出库单）、打包页纸箱、生产看板「用库存」、设置里的新开关
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
        pg.on("pageerror", lambda e: (ERR.append(str(e)), print("  pageerror:", (e.stack or "")[:400]))); pg.on("console", lambda m: ERR.append(m.text) if m.type=="error" and "404" not in m.text and "400" not in m.text else None)
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(B+"/login"); await pg.fill("#username","boss"); await pg.fill("#password","secret1"); await pg.click("#btn"); await pg.wait_for_timeout(1500)
        await pg.evaluate(f"localStorage.setItem('ui_lang','{LANG}')"); await pg.reload(); await pg.wait_for_timeout(3500)
        async def M(sel):
            if LANG=="th": miss.update(await pg.evaluate(JS, sel))
        # 准备：一个产品有 5 个成品库存；下单 2 个 → 自动「用库存发」
        d = await pg.evaluate("""(async()=>{const l=await api('/api/products');const p=await api('/api/products/'+l[0].id);
            await api('/api/config',{json:{review_enabled:false,stock_auto_use:true,inv_ship_out:true}});
            const sku=p.variants[0].sku; await api('/api/stock',{json:{sku,qty:5}});
            const o=await api('/api/orders/manual',{json:{order_no:'UI235-'+Date.now(),order_total:199,items:[{sku,qty:2}]}});
            return {pid:p.id, sku, o}})()""")
        # 产品编辑：选邮政纸箱
        await pg.evaluate(f"openProduct({json.dumps(d['pid'])}, true)"); await pg.wait_for_timeout(2500)
        opts = await pg.evaluate("document.querySelectorAll('#pkg-boxsel option').length")
        if opts != 20: ERR.append(f"v235 box options {opts}")
        await pg.select_option("#pkg-boxsel", "2A"); await pg.wait_for_timeout(300)
        await M("#pkg-box")
        await pg.screenshot(path=SP+f"/v235_editor_{LANG}.png")
        await pg.click("#btn-save"); await pg.wait_for_timeout(1500)
        pb = await pg.evaluate(f"api('/api/products/{d['pid']}').then(p=>p.pack_box)")
        print(" v235 product box:", pb)
        if pb != "2A": ERR.append("v235 product pack_box " + str(pb))
        # 生产看板：用库存的标记
        await pg.evaluate("goTab('production')"); await pg.wait_for_timeout(2000)
        badge = await pg.evaluate("document.querySelector('#tab-production').innerText.includes('📦')")
        if not badge: ERR.append("v235 prod use-stock badge")
        await M("#tab-production")
        # 订单详情：纸箱（自动 = 产品设的 2A）+ 发货出库
        oid = d["o"]["id"]
        await pg.evaluate(f"goTab('orders')"); await pg.wait_for_timeout(1500)
        await pg.evaluate(f"OPS.openOrder({oid})"); await pg.wait_for_timeout(1500)
        st = await pg.evaluate("[!!document.querySelector('.pb-sel'), (document.querySelector('.pb-sel')||{}).value, document.body.innerText.includes('2A')]")
        print(" v235 order box:", st)
        if not (st[0] and st[1] == "" and st[2]): ERR.append(f"v235 order box auto {st}")
        await M("#ord-detail")
        await pg.screenshot(path=SP+f"/v235_order_{LANG}.png", full_page=True)
        await pg.select_option(".pb-sel", "2B"); await pg.wait_for_timeout(1200)
        ob = await pg.evaluate(f"api('/api/orders/{oid}').then(o=>o.box.code)")
        if ob != "2B": ERR.append("v235 change box " + str(ob))
        # 发货 → 出库单
        await pg.evaluate(f"api('/api/orders/{oid}',{{json:{{status:'shipped'}}}})"); await pg.wait_for_timeout(800)
        await pg.evaluate(f"OPS.openOrder({oid})"); await pg.wait_for_timeout(1500)
        out = await pg.evaluate("[!!document.querySelector('#ord-detail [data-invdoc]'), document.querySelector('#ord-detail').innerText.includes('BOX-2B')]")
        print(" v235 order out doc:", out)
        if not all(out): ERR.append(f"v235 ship-out doc in order {out}")
        await M("#ord-detail")
        await pg.evaluate("document.querySelector('#ord-detail [data-invdoc]').scrollIntoView()")
        await pg.screenshot(path=SP+f"/v235_order_out_{LANG}.png")
        await pg.click("#ord-detail [data-invdoc]"); await pg.wait_for_timeout(1200)
        await M("#modal-in")
        await pg.evaluate("MODAL.close()")
        await pg.click("#ord-detail [data-x]"); await pg.wait_for_timeout(300)
        # 打包页：纸箱
        o2 = await pg.evaluate(f"api('/api/orders/manual',{{json:{{order_no:'UI235P-'+Date.now(),order_total:99,items:[{{sku:{json.dumps(d['sku'])},qty:1}}]}}}})")
        await pg.evaluate("goTab('pack')"); await pg.wait_for_timeout(800)
        await pg.fill("#pk-code", o2["order_no"]); await pg.press("#pk-code", "Enter"); await pg.wait_for_timeout(1500)
        pk = await pg.evaluate("[!!document.querySelector('.pk-box .pb-sel'), document.querySelector('#tab-pack').innerText.includes('2A')]")
        print(" v235 pack box:", pk)
        if not all(pk): ERR.append(f"v235 pack box {pk}")
        await M("#tab-pack")
        # 库存 → 货位：一次建两个货架
        await pg.evaluate("goTab('inventory')"); await pg.wait_for_timeout(1500)
        await pg.click("#inv-views [data-iv=locations]"); await pg.wait_for_timeout(1200)
        z = "Q" if LANG == "zh" else "R"
        await pg.click("#loc-bulk"); await pg.wait_for_timeout(500)
        await pg.fill("#lb-zone", z); await pg.fill("#lb-shelf", "1"); await pg.fill("#lb-count", "2"); await pg.fill("#lb-layers", "2"); await pg.fill("#lb-pos", "3")
        await pg.fill("#lb-name", "Test"); await pg.wait_for_timeout(200)
        prev = await pg.evaluate("document.querySelector('#lb-prev').textContent")
        if f"{z}2-02-03" not in prev: ERR.append("v235 bulk preview " + prev)
        await M("#modal-in")
        await pg.click("#lb-ok"); await pg.wait_for_timeout(1500)
        n = await pg.evaluate(f"[document.querySelectorAll('.loc-shelf[data-shelf={z}1] .loc-cell').length, document.querySelectorAll('.loc-shelf[data-shelf={z}2] .loc-cell').length]")
        print(" v235 bulk shelves:", n)
        if n != [6, 6]: ERR.append(f"v235 bulk shelves {n}")
        await M("#tab-inventory")
        await pg.screenshot(path=SP+f"/v235_loc_{LANG}.png", full_page=True)
        # 点格子 → 放物品
        await pg.click(f".loc-shelf[data-shelf={z}1] .loc-cell >> nth=0"); await pg.wait_for_timeout(1200)
        await M("#modal-in")
        val = await pg.evaluate("[...document.querySelectorAll('#loc-put option')].map(o=>o.value).find(v=>v)")
        if not val: ERR.append("v235 no item to put")
        else:
            await pg.select_option("#loc-put", val); await pg.click("#loc-put-ok"); await pg.wait_for_timeout(1500)
            loc = await pg.evaluate(f"api('/api/inv/items/{val}').then(r=>(r.item||r).location)")
            print(" v235 put:", loc)
            if loc != f"{z}1-01-01" and loc != f"{z}1-02-01": ERR.append("v235 put item " + str(loc))
            await M("#modal-in")
        await pg.evaluate("MODAL.close()"); await pg.wait_for_timeout(300)
        await pg.evaluate("INVLOC.render(document.querySelector('#inv-body'))"); await pg.wait_for_timeout(1200)
        if await pg.evaluate("!!document.querySelector('#loc-unassigned')"):
            await pg.click("#loc-unassigned"); await pg.wait_for_timeout(1000); await M("#modal-in"); await pg.evaluate("MODAL.close()")
        # 按货架盘点
        await pg.click(f"[data-stk={z}1]"); await pg.wait_for_timeout(1500)
        stk = await pg.evaluate("[!!document.querySelector('#inv-st-tbl'), document.querySelectorAll('#inv-st-tbl tbody tr').length]")
        print(" v235 shelf stocktake:", stk)
        if not (stk[0] and stk[1] >= 1): ERR.append(f"v235 shelf stocktake {stk}")
        await M("#tab-inventory")
        # 盘点列表（按货架选）
        await pg.click("#inv-views [data-iv=stocktake]"); await pg.wait_for_timeout(1000)
        if await pg.evaluate("!!document.querySelector('#inv-st-back')"): await pg.click("#inv-st-back"); await pg.wait_for_timeout(800)
        await M("#tab-inventory")
        # 纸箱
        await pg.click("#inv-views [data-iv=boxes]"); await pg.wait_for_timeout(1200)
        bx = await pg.evaluate("[document.querySelectorAll('#inv-body tbody tr').length, document.querySelector('#inv-body').innerText.includes('2B')]")
        print(" v235 boxes view:", bx)
        if not (bx[0] == 18 and bx[1]): ERR.append(f"v235 boxes view {bx}")
        await M("#tab-inventory")
        await pg.screenshot(path=SP+f"/v235_boxes_{LANG}.png", full_page=True)
        mk = await pg.evaluate("(document.querySelector('[data-boxmk]')||{}).dataset")
        if mk and mk.get("boxmk"):
            await pg.click(f"[data-boxmk='{mk['boxmk']}']"); await pg.wait_for_timeout(1200)
            if not await pg.evaluate(f"api('/api/inv/items').then(r=>r.items.some(i=>i.code==='BOX-{mk['boxmk']}'))"): ERR.append("v235 box item create")
        # 库存列表：货位一列；物品资料里的货位
        await pg.click("#inv-views [data-iv=items]"); await pg.wait_for_timeout(1200)
        await M("#tab-inventory")
        await pg.evaluate(f"INV.itemModal({val or 'null'})"); await pg.wait_for_timeout(1200)
        if val and not await pg.evaluate(f"document.querySelector('#modal-in').innerText.includes('{z}1-')"): ERR.append("v235 item modal location")
        await M("#modal-in"); await pg.evaluate("MODAL.close()")
        # 单据：订单出库
        await pg.click("#inv-views [data-iv=docs]"); await pg.wait_for_timeout(1200)
        await M("#tab-inventory")
        # 设置：库存（货位、发货出库、另外的包材）、订单（成品库存怎么用）
        for mod in ("inventory", "orders"):
            await pg.evaluate(f"CFG_MOD='{mod}'; goTab('settings')"); await pg.wait_for_timeout(2000)
            await M("#tab-settings")
        ok = await pg.evaluate("document.querySelector('#tab-settings').innerText.includes('stock_auto_use') || !!document.querySelector('[data-k=stock_auto_use],[name=stock_auto_use],#cfg-stock_auto_use')")
        print(" v235 settings stock_auto_use:", ok)
        miss={m for m in miss if not any(x in m for x in ("粉色","荧光绿","UI235"))}
        open(SP+"/miss235.json","w").write(json.dumps(sorted(miss),ensure_ascii=False,indent=0)); print("MISS",len(miss)); print("ERR",ERR[:8])
asyncio.run(main())
