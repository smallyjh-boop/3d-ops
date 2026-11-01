"""单独运行打印机连接（v2.54，打印机多了要和 ERP 分开时用，和客服的 modules/cs/worker.py 一样的做法）：

    PRINTER_WORKER=external              （ERP 那边设置：ERP 里就不连打印机，从数据库读状态）
    python -m core.printer_worker        （LH_DATA_DIR 指向同一个数据目录）

按分组分给几个进程：设置里 printer_workers = {"w2": ["B 区"]}，再运行
    PRINTER_WORKER_ID=w2 python -m core.printer_worker
没分配的分组归默认进程（不设 PRINTER_WORKER_ID 的那个）。
状态写进表 printer_state（每秒一次，只写变了的），ERP 的暂停 / 继续 / 取消 / 开始打印 通过表 printer_cmds 交给这里执行。
打印完自动记录（生产模块的 on_printer_change）也在这里执行。
"""
import os
import sys
import time


def boot():
    """载入 ERP 的代码（配置、数据库、模块的接口和事件，生产模块的「状态变化」回调在 web/common.py 里注册），
    但不跑模块的启动任务（v2.54 复审：以前 import app 会在后台进程里也拉订单、跑 Lazada 任务、迁移……和 ERP 重复）。"""
    os.environ.pop("PRINTER_WORKER", None)      # 自己就是后台进程
    os.environ["LH_NO_MODULE_STARTUP"] = "1"
    os.environ["LH_NO_TPL_SYNC"] = "1"
    import app  # noqa: F401
    from core import printers, production
    if production.on_printer_change not in printers._events:
        printers.on_change(production.on_printer_change)
    return printers


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    wid = argv[0] if argv else os.environ.get("PRINTER_WORKER_ID", "")
    printers = boot()
    mgr = printers.start(worker=True, worker_id=wid)
    print(f"打印机连接后台进程开始运行（进程 id：{wid or '默认'}，Ctrl+C 停止）", flush=True)
    try:
        while True:
            time.sleep(30)
            s = mgr.stats()
            print(f"连接 {s['connected']}/{s['links']} 台", flush=True)
    except KeyboardInterrupt:
        mgr.stop()


if __name__ == "__main__":
    sys.exit(main())
