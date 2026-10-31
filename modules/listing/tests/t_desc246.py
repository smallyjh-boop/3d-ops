# v2.46：详情富文本编辑器里自己插的图片——推送时换成 Lazada 图片空间的网址（本系统产品图上传、外站图搬、Lazada 的不动、换不了的去掉），
# 详情里有图片就不再自动接图；没图片照旧自动接
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/m_desc246"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A  # noqa: F401
from modules.listing import lazada_push as L


class Conn:
    def migrate_image(self, u):
        return "https://lzd/migrated.jpg"


L._lz_img = lambda c, s, pid, im: "https://lzd/" + im["file"]
p = {"id": "X", "images": [{"file": "a b.jpg"}]}
h = ('<p>x</p><img src="/files/X/raw/a%20b.jpg?t=1" style="width:50%"><img src="https://ext.com/z.png">'
     '<img src="https://img.lazcdn.com/q.jpg"><img src="/nope.png">')
out = L.desc_img_urls(h, p, Conn(), {})
ok('src="https://lzd/a b.jpg" style="width:50%"' in out, "own picture uploaded, style kept")
ok("https://lzd/migrated.jpg" in out and "img.lazcdn.com/q.jpg" in out and "nope.png" not in out, f"external migrated, lazada kept, unknown dropped {out}")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
