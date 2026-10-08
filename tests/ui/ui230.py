# v2.30 界面：搬成模块的 6 个功能——页面能打开、设置卡片在、没有 JS 报错、泰文没有漏翻
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
        pg.on("pageerror", lambda e: ERR.append(str(e))); pg.on("console", lambda m: ERR.append(m.text) if m.type=="error" and "404" not in m.text else None)
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(B+"/login"); await pg.fill("#username","boss"); await pg.fill("#password","secret1"); await pg.click("#btn"); await pg.wait_for_timeout(1500)
        await pg.evaluate(f"localStorage.setItem('ui_lang','{LANG}')"); await pg.reload(); await pg.wait_for_timeout(3500)
        # 一打开就加载的：顶部下载桌面版、客服提醒、搜索优化
        top = await pg.evaluate("[!!document.querySelector('#desk-dl'), !!window.CSALERT, !!window.SEO, !!window.DESKTOP]")
        print(" v230 boot:", top)
        if not all(top): ERR.append("v230 boot js")
        PAGES = [("cs","#cs-items"),("csrec","#rec-kind"),("csrep",None),("cskb",None),("fin_overview","#fin-ov"),("fin_book","#fin-bk"),
                 ("purchase","#tab-purchase"),("po_suggest","#tab-purchase"),("po_suppliers","#tab-purchase"),("opschg","#tab-opschg")]
        for tab, sel in PAGES:
            await pg.evaluate(f"goTab('{tab}')"); await pg.wait_for_timeout(1500)
            panel = await pg.evaluate(f"(()=>{{const t='{tab}';const id=(typeof PANEL_OF!=='undefined'&&PANEL_OF[t])||t;const el=document.querySelector('#tab-'+id);return el?[!el.classList.contains('hidden'),el.dataset.ready||'',el.innerText.length]:null}})()")
            print(" v230 page", tab, panel)
            if not panel or not panel[0] or panel[1] != "1" or panel[2] < 10: ERR.append("v230 page "+tab)
            pid = await pg.evaluate(f"(typeof PANEL_OF!=='undefined'&&PANEL_OF['{tab}'])||'{tab}'")
            if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-"+pid))
        await pg.screenshot(path=SP+f"/v230_opschg_{LANG}.png", full_page=True)
        # 设置里的模块卡片
        for cat, sel in (("cs","#cskb-settings"),("accounts","#cs-agents"),("ai","#cur-card"),("addons","#cfg-desk")):
            await pg.evaluate(f"CFG_MOD='{cat}'; goTab('settings')"); await pg.wait_for_timeout(2500)
            n = await pg.evaluate(f"(document.querySelector('{sel}')||{{}}).innerText||''")
            print(" v230 settings", cat, len(n))
            if len(n) < 5: ERR.append("v230 settings "+cat)
            if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-settings"))
        await pg.evaluate("CFG_MOD='ai'; goTab('settings')"); await pg.wait_for_timeout(2500)
        await pg.screenshot(path=SP+f"/v230_ai_{LANG}.png", full_page=True)
        # 关掉搜索优化：编辑页按钮消失
        await pg.evaluate("(async()=>{await api('/api/modules/seo',{json:{on:false}})})()"); await pg.wait_for_timeout(500)
        await pg.reload(); await pg.wait_for_timeout(3000)
        vis = await pg.evaluate("getComputedStyle(document.querySelector('#btn-seo-batch')).display")
        print(" v230 seo off button:", vis)
        if vis != "none": ERR.append("v230 needmod hide")
        await pg.evaluate("(async()=>{await api('/api/modules/seo',{json:{on:true}})})()"); await pg.wait_for_timeout(500)
        open(SP+"/miss230.json","w").write(json.dumps(sorted(miss),ensure_ascii=False,indent=0)); print("MISS",len(miss)); print("ERR",ERR[:8])
asyncio.run(main())
