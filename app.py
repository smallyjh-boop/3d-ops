"""3D 运营管理系统 —— 本地运行的网页工具。启动后浏览器打开 http://127.0.0.1:8765

程序结构（v2.15 起）：
  app.py        入口：版本号、启动服务器
  web/common.py Flask 应用、权限、通用小工具
  web/*.py      系统本身的接口（登录、设置、系统检查、电脑加速、API 密钥、模块管理）
  modules/*/    功能模块（v2.29 起）：每个模块自己的页面、接口、权限、设置、事件、测试；接口路径和以前完全一样
  core/*.py     业务逻辑和数据（主链路的数据层：产品、订单、生产、库存都在这里，模块之间通过 core/chain.py 的事件联动）
"""
VERSION = "2.52.0"   # 改版本号时同时改 static/app.js 的 APP_JS_VERSION、static/api-docs.html 里的示例

from web.common import *  # noqa: F401,F403,E402
import web.integrations, web.system, web.accel, web.modules  # noqa: F401,E402  注册路由（不要用 from web import …，会把 core 的同名模块盖掉）
from core import modules as _modules  # noqa: E402
_modules.load_all(app)   # v2.29：modules/ 文件夹里的功能模块（接口、权限、设置、事件）

def main():
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "127.0.0.1")          # NAS/Docker 里是 0.0.0.0（局域网都能访问）
    in_docker = os.environ.get("LH_DOCKER") == "1"
    url = f"http://127.0.0.1:{port}"
    if not in_docker and not _free_port(port):
        print(f"\n  端口 {port} 被其他程序占用，无法启动。请关闭所有「Listing Helper」黑色窗口后再试，或重启电脑。\n")
        input("  按回车键退出…")
        return
    if host == "0.0.0.0":
        print(f"\n  3D 运营管理系统 v{VERSION} 已启动（局域网模式）：用浏览器打开 http://<这台设备的IP>:{port}\n")
    else:
        print(f"\n  3D 运营管理系统 v{VERSION} 已启动：{url}\n  关闭这个黑色窗口即可退出。\n")
    threading.Thread(target=categories.library, daemon=True).start()
    from core import lazada_sync
    lazada_sync.start_background()   # v2.25：还没下载的 Lazada 类目模板在后台自动下载
    from core import updater
    updater.start_background()       # v2.26：每 12 小时看一下 GitHub 有没有新版本（只提醒）
    if _modules.enabled("prod"):
        printers_mod.start()         # 打印机状态轮询（v2.31：生产模块开着才轮询）
    extras.start_backup()            # 每天自动备份
    from core import preview
    preview.warm_all()               # 开机后把大模型的 3D 预览提前算好（第一次打开就快）
    if "--no-browser" not in sys.argv and not in_docker:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve   # 多人同时使用更稳定
        serve(app, host=host, port=port, threads=16)   # 电脑加速的程序会一直挂着一个「领活」的连接
    except ImportError:
        app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
