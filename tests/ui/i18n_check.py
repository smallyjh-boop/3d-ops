"""界面语言检查：泰文界面不能有漏翻的中文，中文界面不能有泰文系统文字 / 英文代码。
自己准备测试数据（tests/fixtures/base_data.zip）、起一个测试服务器（假 AI），用 Node + Playwright 把每个页面点一遍
（tests/ui/i18n_sweep.js），最后按页面列出问题。

用法（在程序文件夹里）：
    python tests/ui/i18n_check.py                 泰文 + 中文，三个账号（老板 / 上架客服 / 生产）
    python tests/ui/i18n_check.py --lang th       只查泰文
    python tests/ui/i18n_check.py --quick         只看每个页面，不点页签和弹窗（快）
    python tests/ui/i18n_check.py --audit         另外列出 data-notr 里的中文（看有没有把系统文字也标成了原始数据）
需要：Node.js 和 Playwright（npm i playwright && npx playwright install chromium）。
报告：打印出来，同时存成 <临时目录>/i18n_report.json。全部没问题退出码 0，有问题 1，跑不起来 2。
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))


def node_ok():
    node = shutil.which("node")
    if not node:
        return None
    r = subprocess.run([node, "-e", "require('playwright')"], cwd=HERE, capture_output=True, text=True)
    return node if r.returncode == 0 else None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def run(args, base_dir=None, keep=False):
    """准备数据、起服务器、跑检查；返回 (退出码, 输出文字, 报告路径)。"""
    node = node_ok()
    if not node:
        return 2, "SKIP: 没有 Node.js 或 Playwright", None
    T = base_dir or tempfile.mkdtemp(prefix="3dops-i18n-")
    D = os.path.join(T, "i18n_data")
    shutil.rmtree(D, ignore_errors=True)
    v13 = os.path.join(T, "v13")
    if os.path.isdir(v13):
        shutil.copytree(v13, D)
    else:
        import zipfile
        import run_all
        with zipfile.ZipFile(os.path.join(run_all.FIX, "base_data.zip")) as z:
            z.extractall(D)
    os.makedirs(os.path.join(D, "tmp"), exist_ok=True)
    tl = os.path.join(APP, "templates_lazada")
    before = set(os.listdir(tl)) if os.path.isdir(tl) else set()
    port = free_port()
    env = dict(os.environ, PYTHONPATH=APP, PYTHONIOENCODING="utf-8", LH_NO_MODULE_STARTUP="1", LH_NO_TPL_SYNC="1",
               LH_NO_UPDATE_CHECK="1", LH_NO_PRESETS="1")
    env.pop("LH_DOCKER", None)
    log = open(os.path.join(T, "i18n_server.log"), "w")
    srv = subprocess.Popen([sys.executable, os.path.join(HERE, "i18n_server.py"), D, str(port)], cwd=T, env=env,
                           stdout=log, stderr=subprocess.STDOUT)
    rep = os.path.join(T, "i18n_report.json")
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(120):
            try:
                urllib.request.urlopen(base + "/login", timeout=2)
                break
            except Exception:  # noqa: BLE001
                if srv.poll() is not None:
                    return 2, "服务器没起来：\n" + open(os.path.join(T, "i18n_server.log"), encoding="utf-8", errors="replace").read()[-3000:], None
                time.sleep(0.5)
        r = subprocess.run([node, os.path.join(HERE, "i18n_sweep.js"), "--base", base, "--out", rep] + args, cwd=HERE,
                           capture_output=True, text=True, timeout=1800)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode:
            return 2, out, rep
        return (0 if " total=0 " in out else 1), out, rep
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()
        # 这次跑出来的 Lazada 自动模板（templates_lazada/lazada_auto_*.xlsx）删掉，不留在程序文件夹里
        for f in (set(os.listdir(tl)) - before) if os.path.isdir(tl) else []:
            if f.startswith("lazada_auto_") and f.endswith(".xlsx"):
                try:
                    os.remove(os.path.join(tl, f))
                except OSError:
                    pass
        if not keep and not base_dir:
            shutil.rmtree(T, ignore_errors=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    args = []
    if "--lang" in a:
        args += ["--lang", a[a.index("--lang") + 1]]
    if "--users" in a:
        args += ["--users", a[a.index("--users") + 1]]
    for f in ("--quick", "--audit", "--visited"):
        if f in a:
            args += [f, "1"]
    code, out, rep = run(args, keep=True)
    print(out)
    if rep:
        print("报告：", rep)
    sys.exit(code)
