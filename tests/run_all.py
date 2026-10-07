"""3D 运营管理系统 —— 一键跑全部回归测试。

用法（在程序文件夹里）：
    python tests/run_all.py            跑全部
    python tests/run_all.py t_modellib 只跑某几个
测试只用临时文件夹里的测试数据（tests/fixtures），不会碰正式数据。
每次改代码、发版前都跑一遍：全部「通过」才发版。
"""
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
CASES = os.path.join(HERE, "cases")

# 顺序有关系（有几个测试共用同一份数据）；数字 = 预期的 ERR 行数（故意测错误情况的）
ORDER = [("t_modellib", 0), ("t_perm2131", 0), ("t_imgtools", 0), ("t_catalog", 0), ("t_spool", 0), ("t_lst2111", 0),
         ("t_v211", 0), ("api_test", 0), ("t_up", 0), ("t_cs", 0), ("ops_test", 0), ("t_fleet", 0), ("t_v27", 0),
         ("t_resin", 0), ("t_listing", 0), ("t_v1", 0), ("t_ops", 0), ("t_v2141", 0), ("t_calib", 0), ("t_preview", 0), ("t_v216", 0), ("t_inv217", 0), ("t_v218", 0), ("t_lang219", 0), ("t_accel220", 0), ("t_fin221", 0), ("t_v222", 0), ("t_seo223", 0), ("t_cs224", 0), ("t_cat225", 0), ("t_up226", 0), ("v20_test", 3)]


def copy_base(T, name, no_users=False):
    d = os.path.join(T, name)
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(os.path.join(T, "v13"), d)
    if no_users:
        c = sqlite3.connect(os.path.join(d, "app.db"))
        c.execute("DELETE FROM users")
        c.commit()
        c.close()


def prepare(T):
    with zipfile.ZipFile(os.path.join(FIX, "base_data.zip")) as z:
        z.extractall(os.path.join(T, "v13"))
    os.makedirs(os.path.join(T, "v13", "tmp"), exist_ok=True)
    shutil.copy(os.path.join(FIX, "cat.stl"), os.path.join(T, "cat.stl"))
    shutil.copytree(os.path.join(FIX, "ordtest"), os.path.join(T, "ordtest"))
    shutil.copytree(os.path.join(FIX, "v12"), os.path.join(T, "v12"))
    shutil.copy(os.path.join(FIX, "y_live_none_zh.png"), os.path.join(T, "y_live_none_zh.png"))
    shutil.copy(os.path.join(FIX, "bambu_project.3mf"), os.path.join(T, "bambu_project.3mf"))
    for n in ("vl", "vo", "v20", "vf", "vr"):
        copy_base(T, n)


def main():
    want = set(sys.argv[1:])
    T = tempfile.mkdtemp(prefix="3dops-test-")
    print(f"测试数据目录：{T}")
    prepare(T)
    env = dict(os.environ, T3D_TMP=T, T3D_APP=APP, PYTHONPATH=APP, PYTHONIOENCODING="utf-8", LH_NO_PRESETS="1", LH_NO_TPL_SYNC="1", LH_NO_UPDATE_CHECK="1")
    env.pop("LH_DOCKER", None)
    results = []
    t0 = time.time()
    for name, expect_err in ORDER:
        if want and name not in want:
            continue
        if name == "v20_test":
            copy_base(T, "v20", no_users=True)
        t1 = time.time()
        try:
            r = subprocess.run([sys.executable, os.path.join(CASES, name + ".py")], cwd=T, env=env,
                               capture_output=True, text=True, timeout=900)
            out = (r.stdout or "") + (r.stderr or "")
            code = r.returncode
        except subprocess.TimeoutExpired:
            out, code = "超时（15 分钟）", -1
        errs = len(re.findall(r"^\s*ERR\b", out, re.M))
        m = re.search(r"ERRORS (\d+)", out)
        reported = int(m.group(1)) if m else None
        ok = code == 0 and "Traceback" not in out and errs == expect_err and (reported in (None, 0) or expect_err)
        results.append((name, ok, time.time() - t1, out))
        print(f"{'通过' if ok else '失败'}  {name:<12} {time.time() - t1:5.1f}s" + ("" if ok else f"  （ERR {errs} 行，退出码 {code}）"))
        with open(os.path.join(T, name + ".log"), "w", encoding="utf-8") as f:
            f.write(out)
    bad = [r for r in results if not r[1]]
    print(f"\n共 {len(results)} 个，通过 {len(results) - len(bad)} 个，失败 {len(bad)} 个，用时 {time.time() - t0:.0f} 秒")
    for name, _ok, _t, out in bad:
        print(f"\n===== {name} 的输出（最后 40 行）=====")
        print("\n".join(out.splitlines()[-40:]))
    if not bad:
        shutil.rmtree(T, ignore_errors=True)
    else:
        print(f"\n完整输出在：{T}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
