# v2.37.1 浏览器插件：后台给没有插件脚本的标签发消息（刚刷新、框架还没加载）时不能报
# 「Uncaught (in promise) Error: Could not establish connection. Receiving end does not exist.」
# 需要完整的 Chromium（headless shell 不能加载插件）；装不了时跳过。
import asyncio, os, sys, tempfile
from playwright.async_api import async_playwright
EXT = os.path.join(os.environ["T3D_APP"], "extension"); ERR = []
async def main():
    async with async_playwright() as p:
        try:
            ctx = await p.chromium.launch_persistent_context(tempfile.mkdtemp(), headless=True, channel="chromium",
                  args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
        except Exception as e:  # noqa: BLE001
            print(" v2371 skip:", str(e)[:120]); print("ERR", ERR); return
        sw = ctx.service_workers[0] if ctx.service_workers else await ctx.wait_for_event("serviceworker")
        await sw.evaluate("self.__rej=[]; self.addEventListener('unhandledrejection', e => self.__rej.push(String(e.reason && e.reason.message || e.reason)))")
        pg = await ctx.new_page(); await pg.goto(f"chrome-extension://{sw.url.split('/')[2]}/options.html"); await pg.wait_for_timeout(500)
        for t in ("unread-all", "collect-all", "chat-changed"):   # options 页里没有 content.js → 收不到
            await pg.evaluate("t => new Promise(r => { chrome.runtime.sendMessage({type: t}, () => { void chrome.runtime.lastError; r(); }); setTimeout(r, 1500); })", t)
        await pg.wait_for_timeout(800)
        rej = await sw.evaluate("self.__rej"); print(" v2371 unhandled:", rej)
        if rej: ERR.append(f"v2371 unhandled {rej}")
        await ctx.close()
    print("ERR", ERR)
    sys.exit(1 if ERR else 0)
asyncio.run(main())
