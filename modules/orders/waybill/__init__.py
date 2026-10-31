"""平台面单框架（v2.34）：面单从哪来 → 按自己的模板加信息 → 打印（类似 BigSeller 的「自定义面单」）。

  sources.py   面单来源：上传的 PDF（现在就能用）/ 平台接口自动取（Shopee、Lazada、TikTok 接通后）/ 自制面单
  template.py  自定义模板：面单下面加信息区，或面单原样 + 另起一张信息（订单号、SKU×数量、规格、货位、留言、打印次数……）
  render.py    排版：PDF 每页转图片（自动裁白边、横转竖），按模板拼成打印页
  这里         打印记录（每次打印记一条 → 面单上显示「补打 第 N 次」，防止重复贴）、打印入口

以后接平台接口：只要在 core/connectors/<平台>.py 里实现 fetch_label() 并把 LABEL_READY 改成 True，
打印时就会自动去平台取面单，排版、加信息、打印记录都不用再改。
对外：load_template()  save_template(d)  status()  print_html(ids, user)  preview_html(tpl)  awb_image(oid, page)
      record(ids, user, kind)  counts(ids)
"""
import os
import time

from core import db

from . import render, sources, template as T

SCHEMA = """
CREATE TABLE IF NOT EXISTS ord_label_prints (
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, ts REAL, username TEXT, kind TEXT
);
CREATE INDEX IF NOT EXISTS ord_label_prints_o ON ord_label_prints(order_id);
"""


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


# ---------------- 打印记录 ----------------
def counts(ids):
    ids = [int(i) for i in ids or []]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r[0]: r[1] for r in db.conn().execute(
        f"SELECT order_id, COUNT(*) FROM ord_label_prints WHERE order_id IN ({q}) GROUP BY order_id", ids)}


def record(ids, user="", kind=""):
    c = db.conn()
    now = time.time()
    for oid in ids or []:
        c.execute("INSERT INTO ord_label_prints(order_id, ts, username, kind) VALUES(?,?,?,?)", (int(oid), now, user or "", kind))
    c.commit()


# ---------------- 模板 ----------------
def load_template(cfg=None):
    return T.load(cfg)


def save_template(d):
    return T.save(d)


def status():
    return {"sources": sources.status(), "template": load_template(), "renderer": render.available(),
            "fields": [{"id": k, "zh": zh, "th": th} for k, zh, th in T.FIELDS],
            "layouts": [{"id": k, "zh": v[0], "th": v[1]} for k, v in T.LAYOUTS.items()],
            "papers": [{"id": k, "zh": T.PAPER_ZH[k], "th": T.PAPER_TH[k]} for k in T.PAPERS]}


def _inv():
    """库存模块（货位）：开着就用货位排序 / 显示货位。"""
    from core import modules
    return modules.public("inv")


def _sort_key():
    inv = _inv()
    return getattr(inv, "sort_key", None) or (lambda c: (0, str(c)))


def enabled(cfg=None):
    """打印平台面单时要不要按模板排（模板开着、PDF 转图片的组件也装好了）。"""
    return load_template(cfg)["enabled"] and render.available()


# ---------------- 打印 ----------------
def print_html(ids, user=""):
    """勾选的订单 → 平台面单打印页。没有面单的列在页面上方（不打印）。返回 (html, 打了的订单id, 没面单的订单id)。"""
    from core import labels as core_labels, orders as orders_mod
    tpl = load_template()
    inv = _inv()
    entries, missing, have = [], [], []
    orders = [o for o in (orders_mod.get_order(int(i)) for i in ids) if o]
    for o in orders:
        path, why = sources.ensure(o)
        if not path:
            missing.append((o["order_no"], why))
            continue
        have.append(o)
    before = counts([o["id"] for o in have])
    where = {}
    if inv is not None:
        for o in have:
            for it in o.get("items") or []:
                if it.get("sku") and it["sku"] not in where:
                    where[it["sku"]] = inv.where_is(it["sku"])
    aspects = {}
    for o in have:
        path = sources.awb_path(o)
        n = render.page_count(path)
        if tpl["layout"] == "below":
            aspects[o["id"]] = _aspect(path, tpl)
        v = int(os.path.getmtime(path))                      # 换了面单文件，图片地址跟着变
        imgs = [f"/api/waybill/awb/{o['id']}/{p}.png?v={v}" for p in range(n)]
        entries.append((o, imgs, before.get(o["id"], 0) + 1))
    if have:
        ids_have = [o["id"] for o in have]
        record(ids_have, user, "平台面单（自定义）")
        core_labels.mark_printed(ids_have, user, "平台面单（自定义）")
    html = render.compose(entries, tpl, where, _sort_key(), missing, aspects=aspects)
    return html, [o["id"] for o in have], [o["order_no"] for o in orders if o not in have]


def _aspect(path, tpl):
    """面单第一页（裁白边、转向以后）的 高 / 宽。图片本来就要转（有缓存），这里顺便读尺寸。"""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(render.awb_png(path, 0, tpl["crop"], tpl["rotate"])))
        return img.height / img.width if img.width else None
    except Exception:  # noqa: BLE001  读不了就按信息区最少高度排
        return None


def preview_html(tpl=None):
    return render.preview_html(T.clean({**load_template(), **(tpl or {})}), _sort_key())


def awb_image(oid, page=0):
    """订单的平台面单第 page 页 → PNG。"""
    from core import orders as orders_mod
    o = orders_mod.get_order(int(oid))
    path = sources.awb_path(o) if o else None
    if not path:
        raise ValueError("这个订单没有平台面单")
    tpl = load_template()
    return render.awb_png(path, int(page), tpl["crop"], tpl["rotate"])
