# v2.36.1 界面：类目下拉框只放前 600 个，AI 选中的类目排在后面时也要显示为已选（以前显示「未选择」）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import asyncio, json, sys
from playwright.async_api import async_playwright
B="http://127.0.0.1:8799"; SP=T; ERR=[]
LANG=sys.argv[1] if len(sys.argv)>1 else "zh"
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch()
        c=await b.new_context(viewport={"width":1400,"height":900}); pg=await c.new_page()
        pg.on("pageerror", lambda e: (ERR.append(str(e)), print("  pageerror:", (e.stack or "")[:400])))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(B+"/login"); await pg.fill("#username","boss"); await pg.fill("#password","secret1"); await pg.click("#btn"); await pg.wait_for_timeout(1500)
        await pg.evaluate(f"localStorage.setItem('ui_lang','{LANG}')"); await pg.reload(); await pg.wait_for_timeout(3500)
        pid = await pg.evaluate("api('/api/products').then(l=>l[0].id)")
        await pg.evaluate(f"openProduct({json.dumps(pid)}, true)"); await pg.wait_for_timeout(2500)
        # 1000 个类目，当前类目是第 900 个
        r = await pg.evaluate("""(()=>{
            CATS = Array.from({length:1000}, (_, i) => ({id:'t.xlsx|s'+i, cat_id:String(90000+i), name:'类目'+String(i).padStart(4,'0'), path:'X > Y'+i}));
            fillCatSelect('t.xlsx|s900', true);
            const s = document.querySelector('#cat-select');
            const a = [s.value, s.options.length];
            document.querySelector('#cat-filter').value = '9000';        // 筛选后（不含当前类目）也要保留当前类目
            fillCatSelect('t.xlsx|s900', true);
            const b = [s.value, s.options[0].textContent];
            document.querySelector('#cat-filter').value = '';
            fillCatSelect('', true);
            return {a, b, empty: s.value};
        })()""")
        print(" v2361 select:", r)
        if r["a"] != ["t.xlsx|s900", 602]: ERR.append(f"v2361 beyond 600 {r['a']}")
        if r["b"][0] != "t.xlsx|s900" or " 10 " not in r["b"][1]: ERR.append(f"v2361 filtered {r['b']}")
        if r["empty"] != "": ERR.append("v2361 empty")
        await b.close()
    print("ERR", ERR)
    sys.exit(1 if ERR else 0)
asyncio.run(main())
