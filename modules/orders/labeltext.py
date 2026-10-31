"""面单上印的字只用泰文 / 英文（v2.42）：快递员和打包员工看的，不印系统的中文。

商品名、规格：订单里带回来的是平台的文字（Lazada / Shopee 本来就是泰文 / 英文）；手工单、表格导入的可能是中文，
这时按对上的产品换成产品的泰文标题、颜色 / 规格的泰文（颜色表、选项对照）；都换不了就不印（SKU 照印）。
对外：Texts(cfg)  .name(it)  .spec(it)  has_cjk(s)  SHIP_METHOD_TH
"""
import re

from core import codes, store

CJK = re.compile(r"[㐀-鿿豈-﫿]")
SHIP_METHOD_TH = {"pickup": "เข้ารับพัสดุ / Pickup", "dropoff": "ส่งที่สาขา / Drop-off", "self": "ส่งเอง / Self"}


def has_cjk(s):
    return bool(CJK.search(str(s or "")))


class Texts:
    """一次打印用一个（同一个产品只读一次）。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self._p = {}

    def _product(self, it):
        pid = it.get("product_id")
        if not pid:
            return None
        if pid not in self._p:
            try:
                self._p[pid] = store.load(pid)
            except (FileNotFoundError, ValueError, KeyError):
                self._p[pid] = None
        return self._p[pid]

    def _variant(self, it):
        p = self._product(it)
        try:
            return p, (p or {}).get("variants", [])[int(it.get("variant_idx"))]
        except (TypeError, ValueError, IndexError):
            return p, None

    def name(self, it):
        n = str(it.get("name") or "").strip()
        if n and not has_cjk(n):
            return n
        p = self._product(it) or {}
        c = p.get("copy") or {}
        for t in (c.get("title_th"), c.get("title_en")):
            if t and not has_cjk(t):
                return t
        return ""

    def _opt(self, p, zh):
        zh = str(zh or "").strip()
        if not zh:
            return ""
        t = codes.option_th(self.cfg, p or {}, zh)
        if t and not has_cjk(t):
            return t
        col = codes.find_color(self.cfg, zh)
        if col and col[3] and not has_cjk(col[3]):
            return col[3]
        return ""

    def spec(self, it):
        v = str(it.get("variation") or "").strip()
        if v and not has_cjk(v):
            return v
        p, var = self._variant(it)
        if var:
            parts = [self._opt(p, var.get(k)) for k in ("opt1_zh", "opt2_zh")]
            return " ".join(x for x in parts if x)
        return self._opt(p, it.get("color"))
