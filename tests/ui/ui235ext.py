# v2.35 浏览器扩展（v2.9）「面单 PDF 转交」：真 Chromium 加载扩展；一个假的「Shopee 卖家中心」（seller.shopee.test → 本机）下载面单 PDF：
#   普通下载 / 网页生成的 PDF（过一会才删）/ 网页生成后马上删 → 插件弹窗里列出来 → 点「发送到系统」→ 系统按订单号对上订单。
#   别的网站的 PDF 不管；开关关掉不问；「把当前标签页的 PDF 发到系统」；没填密钥时提示。泰文弹窗。
# 只在中文那一轮跑（扩展自己按设置里的语言显示，泰文在最后单独看一下）。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import asyncio, http.server, json, shutil, sys, threading, time, urllib.request
from playwright.async_api import async_playwright
B = "http://127.0.0.1:8799"; SP = T; ERR = []
LANG = sys.argv[1] if len(sys.argv) > 1 else "zh"
if LANG != "zh":
    print("MISS 0"); print("ERR []"); sys.exit(0)

src = open(_os.path.join(APP, "modules", "orders", "tests", "t_waybill.py"), encoding="utf-8").read()
ns = {}
exec(src[src.index("def mk_pdf"):src.index("config.save_config")], ns)
# 测试用的扩展：加上假网站（http://seller.shopee.test）的匹配，其他和发出去的一样
EXT = _os.path.join(T, "ext-test"); shutil.rmtree(EXT, ignore_errors=True); shutil.copytree(_os.path.join(APP, "extension"), EXT)
man = json.load(open(_os.path.join(EXT, "manifest.json"), encoding="utf-8"))
man["content_scripts"][1]["matches"].append("http://seller.shopee.test/*")
json.dump(man, open(_os.path.join(EXT, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False)

import http.cookiejar
CJ = http.cookiejar.CookieJar(); OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CJ))
def call(path, body=None):
    rq = urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    return json.loads(OP.open(rq).read())
call("/api/auth/login", {"username": "boss", "password": "secret1"})
call("/api/config", {"review_enabled": False})
sku = call("/api/products/" + call("/api/products")[0]["id"])["variants"][0]["sku"]
stamp = str(int(time.time()))[-5:]
NOS = [f"EXT-{stamp}{i}" for i in range(1, 6)]
IDS = {no: call("/api/orders/manual", {"order_no": no, "order_total": 99, "items": [{"sku": sku, "qty": 1}]})["id"] for no in NOS}
KEY = call("/api/apikeys", {"name": "Nok"})["key"]

PAGE = """<!doctype html><meta charset=utf-8><title>fake seller</title>
<a id=h href="/f/%s.pdf" download>http pdf</a><button id=b1>blob later revoke</button><button id=b2>blob revoke now</button>
<script>
async function blobDl(path, name, now) {
  const b = await (await fetch(path)).blob();
  const u = URL.createObjectURL(new Blob([b], {type: "application/pdf"}));
  const a = document.createElement("a"); a.href = u; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  if (now) URL.revokeObjectURL(u); else setTimeout(() => URL.revokeObjectURL(u), 40000);
}
b1.onclick = () => blobDl("/f/%s.pdf", "awb_blob.pdf", false);
b2.onclick = () => blobDl("/f/%s.pdf", "awb_now.pdf", true);
</script>""" % (NOS[0], NOS[1], NOS[2])


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/f/"):
            no = self.path[3:].split(".")[0]
            body = ns["mk_pdf"]([(283, 425, ns["label_ops"](0, 0, 283, 425, no, "TH" + no[-5:]))])
            self.send_response(200); self.send_header("Content-Type", "application/pdf"); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body); return
        body = PAGE.encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8798), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
SELLER = "http://seller.shopee.test:8798"


def chk(b, m):
    print((" ok  " if b else " ERR ") + m)
    if not b:
        ERR.append(m)


async def main():
    ud = _os.path.join(T, "ext-profile"); shutil.rmtree(ud, ignore_errors=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(ud, channel="chromium", headless=True, accept_downloads=True, args=[
            f"--disable-extensions-except={EXT}", f"--load-extension={EXT}",
            "--host-resolver-rules=MAP seller.shopee.test 127.0.0.1, MAP other.test 127.0.0.1"])
        sw = ctx.service_workers[0] if ctx.service_workers else await ctx.wait_for_event("serviceworker", timeout=15000)
        ext_id = sw.url.split("/")[2]
        opt = await ctx.new_page()
        opt.on("pageerror", lambda e: ERR.append("popup: " + str(e)))
        await opt.goto(f"chrome-extension://{ext_id}/options.html")
        await opt.evaluate("""(k) => chrome.storage.sync.set({server: "http://127.0.0.1:8799", key: k, lang: "zh", label_forward: true})""", KEY)
        send = lambda m: opt.evaluate("(m) => new Promise((r) => chrome.runtime.sendMessage(m, r))", m)

        async def wait_list(n, t=8):
            for _ in range(t * 4):
                r = await send({"type": "label-list"})
                if len(r["data"]["items"]) >= n:
                    return r
                await asyncio.sleep(0.25)
            return await send({"type": "label-list"})

        async def download(pg, sel):
            async with pg.expect_download() as dl:
                await pg.click(sel)
            await (await dl.value).path()

        pg = await ctx.new_page()
        await pg.goto(SELLER + "/")
        # 1) 普通下载
        await download(pg, "#h")
        items = (await wait_list(1))["data"]["items"]
        chk(len(items) == 1 and items[0]["site"] == "Shopee", f"http pdf listed {items}")
        res = await send({"type": "label-send", "id": items[0]["id"]}) if items else {}
        chk(bool(res.get("ok") and res["data"]["ok"] and NOS[0] in res["data"]["msg"]), f"sent {res}")
        o = call(f"/api/orders/{IDS[NOS[0]]}")
        chk(o.get("label_file") == f"{IDS[NOS[0]]}.pdf", "label stored on the order")
        chk(any(x.get("action") == "上传平台面单" and "插件 · Shopee" in (x.get("detail") or "") for x in o.get("log") or []), "order log: via plugin")
        # 2) 网页生成的 PDF（40 秒后才删）、3) 生成后马上删（点下载那一下就读好了）
        for sel, no in (("#b1", NOS[1]), ("#b2", NOS[2])):
            await download(pg, sel)
            items = (await wait_list(1))["data"]["items"]
            chk(len(items) == 1, f"{sel} blob pdf listed")
            if items:
                res = await send({"type": "label-send", "id": items[0]["id"]})
                chk(res["data"]["ok"] and no in res["data"]["msg"], f"{sel} sent {res['data']['msg']}")
        # 不用：丢掉
        await download(pg, "#b1")
        for x in (await wait_list(1))["data"]["items"]:
            await send({"type": "label-drop", "id": x["id"]})
        chk(not (await send({"type": "label-list"}))["data"]["items"], "drop")
        # 别的网站的 PDF 不管
        pg2 = await ctx.new_page(); await pg2.goto("http://other.test:8798/")
        await download(pg2, "#h"); await asyncio.sleep(1.5)
        chk(not (await send({"type": "label-list"}))["data"]["items"], "other site ignored")
        # 开关关掉就不问
        await opt.evaluate("chrome.storage.sync.set({label_forward: false})")
        await download(pg, "#h"); await asyncio.sleep(1.5)
        chk(not (await send({"type": "label-list"}))["data"]["items"], "switch off -> not captured")
        await opt.evaluate("chrome.storage.sync.set({label_forward: true})")
        # 当前标签页打开的 PDF
        pg3 = await ctx.new_page()
        try:
            await pg3.goto(SELLER + f"/f/{NOS[3]}.pdf")
        except Exception:  # noqa: BLE001  无头模式下 PDF 可能直接变成下载
            pass
        await pg3.bring_to_front()
        res = await send({"type": "label-send-tab"})
        chk(res["ok"] and res["data"]["ok"] and NOS[3] in res["data"]["msg"], f"send current tab {res['data'].get('msg')}")
        await pg.bring_to_front()
        res = await send({"type": "label-send-tab"})
        chk(res["ok"] and not res["data"]["ok"] and "不是 PDF" in res["data"]["msg"], "non-pdf tab refused")
        # 没填密钥
        await opt.evaluate("chrome.storage.sync.set({key: ''})")
        await download(pg, "#h")
        items = (await wait_list(1))["data"]["items"]
        res = await send({"type": "label-send", "id": items[0]["id"]}) if items else {"data": {"ok": True, "msg": ""}}
        chk(not res["data"]["ok"] and "密钥" in res["data"]["msg"], "no key -> hint")
        # 弹窗：中文 / 泰文
        await opt.reload(); await opt.wait_for_timeout(800)
        body = await opt.inner_text("body")
        chk("面单 PDF 转交" in body and "发送到系统" in body, "popup lists pending label")
        await opt.screenshot(path=SP + "/v235_ext_popup_zh.png", full_page=True)
        await opt.evaluate("chrome.storage.sync.set({lang: 'th'})"); await opt.reload(); await opt.wait_for_timeout(800)
        th = await opt.inner_text("body")
        chk("ส่งใบปะหน้า PDF เข้าระบบ" in th and "ส่งเข้าระบบ" in th and "最近下载" not in th, "popup thai")
        await opt.screenshot(path=SP + "/v235_ext_popup_th.png", full_page=True)
        await ctx.close()


try:
    asyncio.run(main())
finally:
    srv.shutdown()
print("MISS 0"); print("ERR", ERR[:8])
