"""界面测试（可选，需要 Playwright + Chromium）：起一个测试服务器（端口 8799，假 AI），中文、泰文各跑一遍，
检查：页面有没有 JavaScript 报错、泰文界面有没有漏翻的中文。截图在输出的测试数据目录里。
用法：python tests/ui/run_ui.py
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import run_all  # noqa: E402

T = tempfile.mkdtemp(prefix="3dops-ui-")
run_all.prepare(T)
for f in ("prod.jpg", "prod2.jpg"):
    shutil.copy(os.path.join(run_all.FIX, f), os.path.join(T, f))
run_all.copy_base(T, "v20", no_users=True)
env = dict(os.environ, T3D_TMP=T, T3D_APP=run_all.APP, PYTHONPATH=run_all.APP, PYTHONIOENCODING="utf-8", LH_NO_PRESETS="1", LH_NO_TPL_SYNC="1", LH_NO_UPDATE_CHECK="1",
           LH_EXTRA_MODULES=os.path.join(run_all.APP, "tests", "fixtures", "demomods"))
subprocess.run([sys.executable, os.path.join(HERE, "seed2131.py")], cwd=T, env=env, check=True)
srv = subprocess.Popen([sys.executable, os.path.join(HERE, "run_cs_server.py")], cwd=T, env=env,
                       stdout=open(os.path.join(T, "server.log"), "w"), stderr=subprocess.STDOUT)
bad = 0
SCRIPTS = [a for a in sys.argv[1:] if a.startswith("ui")] or ["ui214", "ui228", "ui229", "ui230", "ui231", "ui232", "ui233", "ui234", "ui235", "ui235ext", "ui2361", "ui2371ext"]
try:
    time.sleep(6)
    for lang in ("zh", "th"):
        out, miss, errs, rc = "", [], False, 0
        for script in SCRIPTS:
            r = subprocess.run([sys.executable, os.path.join(HERE, script + ".py"), lang], cwd=T, env=env, capture_output=True, text=True, timeout=900)
            o = r.stdout + r.stderr
            out += o
            mf = os.path.join(T, "miss" + script[2:] + ".json")
            if lang == "th" and os.path.exists(mf):
                miss += [m for m in json.load(open(mf, encoding="utf-8")) if m not in miss]
            errs = errs or "ERR []" not in o
            rc = rc or r.returncode
        r = type("R", (), {"returncode": rc})
        ok = r.returncode == 0 and not errs and not miss
        bad += not ok
        print(f"{'通过' if ok else '失败'}  界面测试 {lang}" + ("" if ok else f"：{'有 JS 报错 ' if errs else ''}{('漏翻 ' + str(len(miss)) + ' 处：' + '、'.join(miss[:10])) if miss else ''}"))
        if not ok:
            print("\n".join(out.splitlines()[-25:]))
finally:
    srv.terminate()
print(f"截图和日志在：{T}")
sys.exit(1 if bad else 0)
