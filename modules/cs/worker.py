"""单独运行客服后台任务（v2.46，消息多了要和 ERP 分开时用）：

    CS_WORKER=external  （ERP 那边设置，ERP 里就不跑客服后台任务）
    python -m modules.cs.worker        （在能访问同一个数据目录的机器 / 容器里运行，LH_DATA_DIR 指向同一个数据目录）

可以开多个，任务表会保证同一个任务只被一个进程拿到。
"""
import sys


def main():
    import app  # noqa: F401  载入配置、数据库、模块
    from modules.cs.logic import data, jobs
    data.init()
    print("客服后台任务开始运行（Ctrl+C 停止）")
    jobs.loop()


if __name__ == "__main__":
    sys.exit(main())
