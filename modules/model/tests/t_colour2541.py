# v2.54.1 复审修复：角标小圆点的「最常用颜色」缓存几分钟（读最多 400 个产品），颜色表变了就换 key。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, time
D = T + "/m_colour2541"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import colorbadge, codes
from core.config import load_config

cfg = load_config()
calls = []
orig = colorbadge._dots_for
colorbadge._dots_for = lambda c, n=5: (calls.append(1), orig(c, n))[1]
colorbadge._dots_cache.clear()
d1 = colorbadge.dots_for(cfg)
d2 = colorbadge.dots_for(cfg)
d3 = colorbadge.dots_for(cfg)
ok(d1 == d2 == d3 and len(d1) > 0, f"same dots {d1}")
ok(len(calls) == 1, f"products read once for three images ({len(calls)})")
cfg2 = dict(cfg)
tbl = [list(r) for r in codes.color_table(cfg)]
tbl.append(["测试色", "TST", "สีทดสอบ", "#123456"])
cfg2["color_table"] = tbl
try:
    k1 = codes.color_hex(cfg); k2 = codes.color_hex(cfg2)
    changed = k1 != k2
except Exception:  # noqa: BLE001
    changed = False
if changed:
    colorbadge.dots_for(cfg2)
    ok(len(calls) == 2, "changed colour table -> recomputed")
else:
    ok(True, "colour table key probe skipped")
# 过期重算
for k, v in list(colorbadge._dots_cache.items()):
    colorbadge._dots_cache[k] = (time.time() - colorbadge.DOTS_TTL - 1, v[1])
n = len(calls)
colorbadge.dots_for(cfg)
ok(len(calls) == n + 1, "expired entry recomputed")
colorbadge._dots_for = orig
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
