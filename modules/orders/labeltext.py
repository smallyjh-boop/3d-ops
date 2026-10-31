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

    def image(self, it):
        """商品图（面单商品清单的图片列）：对上的产品的第一张图；对不上返回空。"""
        p = self._product(it) or {}
        im = next((x for x in p.get("images") or [] if x.get("file")), None)
        if not im:
            return ""
        return f"/files/{p['id']}/{'out' if im.get('processed') else 'raw'}/{im['file']}"

    def spec(self, it):
        """规格（v2.44.2 缩写）：对得上 ERP 产品就用 ERP 的颜色 / 规格（泰文，颜色在前）；
        对不上就整理平台的写法（去掉「Variation1:」这种前缀、颜色排前、去掉括号说明和默认规格）。每段最多 16 个字。"""
        p, var = self._variant(it)
        if var:
            parts = [short(self._opt(p, var.get(k))) for k in ("opt1_zh", "opt2_zh")]
            out = " / ".join(x for x in parts if x)
            if out:
                return out
        v = str(it.get("variation") or "").strip()
        if v and not has_cjk(v):
            return platform_spec(v)
        return short(self._opt(p, it.get("color")))


DEFAULT_SPEC = {"มาตรฐาน", "standard", "default", "ปกติ", "ทั่วไป", "-", "none", "no", "n/a", "one size", "free size"}
COLOR_KEY = re.compile(r"colou?r|สี|色", re.I)


def short(v, n=16):
    """一段规格缩短：去掉括号里的补充说明，默认规格（标准 / Standard）不印，太长截断。"""
    v = re.sub(r"\s*[\(（\[][^)）\]]*[\)）\]]", "", str(v or "")).strip(" ,;/")
    if v.lower() in DEFAULT_SPEC:
        return ""
    return v if len(v) <= n else v[:n - 1].rstrip() + "…"


def platform_spec(v):
    """平台带回来的规格文字 → 缩写：
    「Variation2:มาตรฐาน, Variation1:สีสุ่ม (คละสี)」→「สีสุ่ม」；「Color Family:Black, Size:L」→「Black / L」。"""
    parts = [x.strip() for x in re.split(r"[,;，；]\s*", v) if x.strip()]
    kv = []
    for i, x in enumerate(parts):
        m = re.match(r"^([^:：]{1,30})\s*[:：]\s*(.+)$", x)
        key, val = (m.group(1).strip(), m.group(2)) if m else ("", x)
        num = re.search(r"(\d+)\s*$", key)
        order = int(num.group(1)) if num else (0 if COLOR_KEY.search(key) else 50 + i)
        kv.append((order, val))
    vals = [short(val) for _o, val in sorted(kv, key=lambda t: t[0])]
    return " / ".join(x for x in vals if x)
