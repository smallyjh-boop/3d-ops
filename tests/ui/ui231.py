# v2.31 界面：主链路模块（商品、上架导出、订单、生产、库存）的页面都能打开；关掉生产 / 库存 / 上架导出后其它页面没有 JS 报错
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import asyncio, json, sys
from playwright.async_api import async_playwright
B="http://127.0.0.1:8799"; SP=T; ERR=[]
JS=open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),"th_missing.js"),encoding="utf-8").read()
LANG=sys.argv[1] if len(sys.argv)>1 else "zh"
TABS=["library","export","orders","pack","handover","aftersales","buyers","profit","production","printers","files","recipes","quality","inventory","materials","stock","dashboard"]
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); miss=set()
        c=await b.new_context(viewport={"width":1400,"height":900}); pg=await c.new_page()
        pg.on("pageerror", lambda e: ERR.append(str(e))); pg.on("console", lambda m: ERR.append(m.text) if m.type=="error" and "404" not in m.text else None)
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(B+"/login"); await pg.fill("#username","boss"); await pg.fill("#password","secret1"); await pg.click("#btn"); await pg.wait_for_timeout(1500)
        await pg.evaluate(f"localStorage.setItem('ui_lang','{LANG}')"); await pg.reload(); await pg.wait_for_timeout(3500)
        for t in TABS:
            await pg.evaluate(f"goTab('{t}')"); await pg.wait_for_timeout(900)
            st = await pg.evaluate(f"(()=>{{const b=document.querySelector('#subnav .tab[data-tab={t}]');const el=document.querySelector('#tab-{t}');return [!!b, el?!el.classList.contains('hidden'):false, el?el.innerText.length:0]}})()")
            if not (st[0] and st[1] and st[2] > 5): ERR.append(f"v231 tab {t} {st}")
            if LANG=="th" and t != "dashboard": miss|=set(await pg.evaluate(JS,f"#tab-{t}"))   # 工作台的耗材提醒里有测试数据的中文颜色名
        order = await pg.evaluate("[...document.querySelectorAll('#subnav .tab[data-mod=inv]')].map(x=>x.dataset.tab)")
        print(" v231 inv menu order:", order)
        if order[:3] != ["inventory","materials","stock"]: ERR.append("v231 inv order")
        # 打开一个产品：编辑页正常
        await pg.evaluate("goTab('library')"); await pg.wait_for_timeout(800)
        await pg.click("#lib-table tbody tr td a, #lib-table tbody tr"); await pg.wait_for_timeout(2500)
        ed = await pg.evaluate("[!document.querySelector('#tab-edit').classList.contains('hidden'), getComputedStyle(document.querySelector('#recipe-wrap')).display]")
        print(" v231 editor:", ed)
        if not ed[0] or ed[1] == "none": ERR.append("v231 editor")
        # 关掉生产 + 库存 + 上架导出
        for m in ("prod","inv","listing"):
            await pg.evaluate(f"(async()=>{{await api('/api/modules/{m}',{{json:{{on:false}}}})}})()"); await pg.wait_for_timeout(300)
        await pg.reload(); await pg.wait_for_timeout(3500)
        gone = await pg.evaluate("['production','inventory','export','materials'].map(t=>!document.querySelector('#subnav .tab[data-tab='+t+']') && !document.querySelector('#tab-'+t))")
        print(" v231 off gone:", gone)
        if not all(gone): ERR.append("v231 off menus")
        for t in ("library","orders","pack","dashboard","profit"):
            await pg.evaluate(f"goTab('{t}')"); await pg.wait_for_timeout(900)
        await pg.evaluate("goTab('library')"); await pg.wait_for_timeout(800)
        await pg.click("#lib-table tbody tr td a, #lib-table tbody tr"); await pg.wait_for_timeout(2500)
        rw = await pg.evaluate("getComputedStyle(document.querySelector('#recipe-wrap')).display")
        print(" v231 recipe panel when prod off:", rw)
        if rw != "none": ERR.append("v231 recipe hidden")
        await pg.evaluate("CFG_MOD='modules'; goTab('settings')"); await pg.wait_for_timeout(2000)
        await pg.screenshot(path=SP+f"/v231_modules_{LANG}.png", full_page=True)
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-settings"))
        for m in ("listing","inv","pur","prod"):
            await pg.evaluate(f"(async()=>{{await api('/api/modules/{m}',{{json:{{on:true}}}})}})()"); await pg.wait_for_timeout(300)
        await pg.reload(); await pg.wait_for_timeout(3000)
        back = await pg.evaluate("!!document.querySelector('#tab-production') && !!document.querySelector('#subnav .tab[data-tab=export]')")
        if not back: ERR.append("v231 back on")
        miss={m for m in miss if not any(x in m for x in ("粉色","荧光绿"))}   # 测试数据里的中文颜色名（用户自己的数据）
        open(SP+"/miss231.json","w").write(json.dumps(sorted(miss),ensure_ascii=False,indent=0)); print("MISS",len(miss)); print("ERR",ERR[:8])
asyncio.run(main())
