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
        await pg.evaluate(f"localStorage.setItem('ui_lang','{LANG}')"); await pg.reload(); await pg.wait_for_timeout(3000)
        # 模块菜单 + 按需加载
        has = await pg.evaluate("!!document.querySelector('#subnav .tab[data-tab=demo_page]')")
        loaded_before = await pg.evaluate("!!(window.MODS && window.MODS.demo)")
        await pg.evaluate("goTab('demo_page')"); await pg.wait_for_timeout(1500)
        txt = await pg.inner_text("#tab-demo_page")
        print(" v229 menu:", has, "lazy:", not loaded_before, "page:", txt.replace("\n"," | "))
        if not has or loaded_before or ("演示已加载" not in txt and "โหลดสาธิตแล้ว" not in txt): ERR.append("v229 module page")
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-demo_page")); miss|=set(await pg.evaluate(JS,"#subnav"))
        # 设置 → 模块管理
        await pg.evaluate("CFG_MOD='modules'; goTab('settings')"); await pg.wait_for_timeout(2500)
        rows = await pg.evaluate("[...document.querySelectorAll('[data-cfgext=modules] tbody tr')].map(r=>r.innerText.replace(/\\s+/g,' '))")
        print(" v229 manager:", rows)
        if len(rows) < 4 or not any("Tailscale" in r for r in rows): ERR.append("v229 manager rows")
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-settings"))
        await pg.screenshot(path=SP+f"/v229_modules_{LANG}.png", full_page=True)
        # 关掉演示模块 → 刷新后菜单消失；再打开
        await pg.click("[data-modsw=demo]"); await pg.wait_for_timeout(1200)
        await pg.reload(); await pg.wait_for_timeout(3000)
        gone = await pg.evaluate("!document.querySelector('#subnav .tab[data-tab=demo_page]')")
        print(" v229 off -> menu gone:", gone)
        if not gone: ERR.append("v229 disable hides menu")
        await pg.evaluate("(async()=>{await api('/api/modules/demo',{json:{on:true}})})()"); await pg.wait_for_timeout(500)
        # 设置 → 通用：Tailscale 设置卡片（模块自己的卡片）
        await pg.evaluate("CFG_MOD='general'; goTab('settings')"); await pg.wait_for_timeout(2500)
        card = await pg.evaluate("(document.querySelector('[data-modcard=tailscale]')||{}).innerText||''")
        print(" v229 ts card:", card[:120].replace("\n"," | "))
        if "tag:3dops" not in card: ERR.append("v229 tailscale card")
        if LANG=="th": miss|=set(await pg.evaluate(JS,"#tab-settings"))
        await pg.screenshot(path=SP+f"/v229_general_{LANG}.png", full_page=True)
        open(SP+"/miss229.json","w").write(json.dumps(sorted(miss),ensure_ascii=False,indent=0)); print("MISS",len(miss)); print("ERR",ERR[:8])
asyncio.run(main())
