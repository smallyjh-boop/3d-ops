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
        # ---- v2.28：桌面客户端（假的 pywebview）+ 拖文件上传 ----
        dc=await b.new_context(viewport={"width":1400,"height":900}); dp=await dc.new_page()
        dp.on("pageerror", lambda e: ERR.append("desk: "+str(e)))
        await dc.add_init_script("""window.__D={calls:[]};const st={state:'未配对',done:0,failed:0,current:'',log:['a'],paused:false,share:false,name:''};
          const api={info:async()=>({desktop:true,version:'x',device_id:'d'.repeat(32),device_name:'TEST-PC',paired_user:window.__D.user||'',server:location.origin,servers:[location.origin],autostart:true,accel:st}),
            paired:async(s,k,n,u)=>{window.__D.calls.push(['paired',s,k.slice(0,3),n,u]);window.__D.user=u;st.state='在线';st.name=n;return true},
            notify:async(t,m)=>{window.__D.calls.push(['notify',t,m]);return true},open_window:async(u)=>{window.__D.calls.push(['win',u]);return true},
            open_external:async(u)=>{window.__D.calls.push(['ext',u]);return true},open_local:async(u)=>{window.__D.calls.push(['local',u]);return {ok:true,path:'C:/x'}},
            set_option:async(k,v)=>{st[k]=v;window.__D.calls.push(['opt',k,v]);return api.info()},show_folder:async()=>true,switch_server:async()=>true};
          window.pywebview={api};document.addEventListener('DOMContentLoaded',()=>setTimeout(()=>window.dispatchEvent(new Event('pywebviewready')),50));""")
        await dp.goto(B+"/login"); await dp.fill("#username","boss"); await dp.fill("#password","secret1"); await dp.click("#btn"); await dp.wait_for_timeout(1500)
        await dp.evaluate(f"localStorage.setItem('ui_lang','{LANG}')"); await dp.reload(); await dp.wait_for_timeout(5000)
        calls = await dp.evaluate("window.__D.calls")
        chip = await dp.inner_text("#desk-chip") if await dp.locator("#desk-chip").count() else ""
        hid = await dp.evaluate("getComputedStyle(document.querySelector('#desk-dl')).display")
        print(" v228 desk:", [c[:2]+c[3:] for c in calls][:4], chip, hid)
        if not any(c[0]=="paired" and c[4]=="boss" for c in calls) or not chip or hid!="none": ERR.append("v228 desktop pairing/chip")
        await dp.evaluate("new Notification('ทดสอบ',{body:'hello'})"); await dp.wait_for_timeout(200)
        await dp.evaluate("window.open('/print/jobs?ids=1')"); await dp.wait_for_timeout(200)
        await dp.evaluate("openProduct('3DP0001', true)"); await dp.wait_for_timeout(3500)
        await dp.evaluate("goTab('files')"); await dp.wait_for_timeout(2500)
        lk = dp.locator('a[href*="/model/download"]').first
        if await lk.count(): await lk.click(); await dp.wait_for_timeout(1500)
        calls = await dp.evaluate("window.__D.calls")
        kinds=[c[0] for c in calls]; print(" v228 calls:", kinds)
        if "notify" not in kinds or "win" not in kinds: ERR.append("v228 notify/window")
        if await lk.count() and not any(c[0]=="local" and c[1].startswith("/api/desktop/dl/") for c in calls): ERR.append("v228 open local")
        await dp.click("#desk-chip"); await dp.wait_for_timeout(500)
        if LANG=="th": miss|=set(await dp.evaluate(JS,"#modal-in"))
        await dp.screenshot(path=SP+f"/v228_desk_{LANG}.png")
        await dp.click("[data-dopt=share]"); await dp.wait_for_timeout(300)
        if not any(c[0]=="opt" and c[1]=="share" and c[2] for c in await dp.evaluate("window.__D.calls")): ERR.append("v228 option")
        await dp.keyboard.press("Escape")
        # 拖一张图片到产品编辑页 → 走「选择图片上传」
        await dp.evaluate("openProduct('3DP0001', true)"); await dp.wait_for_timeout(3000)
        n0 = await dp.locator("#img-grid .img-card").count()
        await dp.evaluate("""(async()=>{const b=await (await fetch('/static/vendor/three/three.module.min.js')).blob();
          const c=document.createElement('canvas');c.width=c.height=64;c.getContext('2d').fillRect(0,0,64,64);
          const png=await new Promise(r=>c.toBlob(r,'image/png'));const f=new File([png],'drop.png',{type:'image/png'});
          const dt=new DataTransfer();dt.items.add(f);
          window.dispatchEvent(new DragEvent('dragenter',{dataTransfer:dt}));
          window.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,cancelable:true}));})()""")
        await dp.wait_for_timeout(5000)
        n1 = await dp.locator("#img-grid .img-card").count()
        print(" v228 drop images:", n0, "->", n1)
        if n1 <= n0: print(" v228 inputs:", await dp.evaluate("[...document.querySelectorAll('input[type=file]')].map(i=>[i.id,i.disabled,!!i.closest('.hidden'),!!i.closest('.panel:not(.hidden)')]).filter(x=>x[3])"))
        if n1 <= n0: ERR.append("v228 drop upload")
        if LANG=="th": miss|=set(await dp.evaluate(JS,"header"))
        # 浏览器里（不是桌面端）：顶部「下载桌面版」→ 两个选项
        wc=await b.new_context(viewport={"width":1400,"height":900}); wp=await wc.new_page()
        wp.on("pageerror", lambda e: ERR.append("web: "+str(e)))
        await wp.goto(B+"/login"); await wp.fill("#username","boss"); await wp.fill("#password","secret1"); await wp.click("#btn"); await wp.wait_for_timeout(1500)
        await wp.evaluate(f"localStorage.setItem('ui_lang','{LANG}')"); await wp.reload(); await wp.wait_for_timeout(3000)
        await wp.click("#desk-dl"); await wp.wait_for_timeout(500)
        hrefs = await wp.evaluate("[...document.querySelectorAll('#modal-in a')].map(a=>a.getAttribute('href'))")
        print(" v228 choose:", hrefs)
        if hrefs != ["/api/desktop/package", "/api/accel/package?personal=1"]: ERR.append("v228 download chooser")
        if LANG=="th": miss|=set(await wp.evaluate(JS,"#modal-in"))
        await wp.screenshot(path=SP+f"/v228_choose_{LANG}.png")
        await wc.close()
        await dc.close()
        open(SP+"/miss228.json","w").write(json.dumps(sorted(miss),ensure_ascii=False,indent=0)); print("MISS",len(miss)); print("ERR",ERR[:8])
asyncio.run(main())
