# v2.49.1：界面语言检查——泰文界面每个页面、页签、常用弹窗 / 抽屉、手机页都不能有漏翻的中文；
# 中文界面不能有泰文系统文字和直接显示出来的英文代码（例如 product / custom / order_status）。
# 用 Node + Playwright（tests/ui/i18n_sweep.js，见 tests/ui/i18n_check.py）；没装 Node 或 Playwright 就跳过。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys
sys.path.insert(0, os.path.join(APP, "tests", "ui"))
sys.path.insert(0, os.path.join(APP, "tests"))
import i18n_check
E = 0
def ok(b, m):
    global E; print(("OK  " if b else "ERR ") + m); E += (not b)

if not i18n_check.node_ok():
    print("SKIP: 没有 Node.js 或 Playwright（npm i playwright），不检查界面语言")
else:
    code, out, rep = i18n_check.run(["--zhusers", "boss", "--wait", "500"], base_dir=T)
    tail = "\n".join(l for l in out.splitlines() if l.strip())
    print(tail[-12000:])
    ok(code != 2, "i18n sweep ran")
    ok(code == 0, "no untranslated / wrong-language text on any page (report: " + str(rep) + ")")
    ok("pageerror" not in out, "no JS errors while clicking through")
print("ERRORS", E)
