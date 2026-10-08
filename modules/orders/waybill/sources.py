"""平台面单从哪来（v2.34）。

不管从哪来，面单都存成同一个地方：data/labels/<订单id>.pdf，订单的 label_file 记文件名。
  upload    订单页「上传平台面单」：平台 / BigSeller 批量打印的 PDF，按每页文字里的订单号 / 运单号自动拆到每个订单
            （core/labels.import_pdf，v2.x 就有）
  shopee / lazada / tiktok
            店铺对接（core/connectors）里每个平台的 fetch_label(订单)：从平台开放接口取面单。
            接通前 LABEL_READY = False，这里显示「未接入」；接通后打印时自动去取，取到就存起来，以后不用再取。
  self      自制面单（carriers.py）：手工单、自己找快递的单
对外：awb_path(order)  ensure(order)  status()  save_doc(order, doc, source)
"""
import io
import os

from core import connectors, db
from core import labels as core_labels


def awb_path(order):
    """这个订单已经有的面单 PDF（上传的或接口取到的）；没有返回 None。"""
    f = (order or {}).get("label_file")
    p = os.path.join(core_labels.LABEL_DIR, f) if f else None
    return p if p and os.path.exists(p) else None


def _shops(platform):
    try:
        return db.conn().execute("SELECT id, name FROM shops WHERE platform=? AND enabled=1", (platform or "",)).fetchall()
    except Exception:  # noqa: BLE001  还没建过店铺表
        return []


def _shop_id(order):
    """订单对应的已启用店铺：同平台；有好几个店铺时按店铺名对。"""
    rows = _shops(order.get("platform"))
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]["id"]
    m = [r for r in rows if (r["name"] or "").strip() == (order.get("shop") or "").strip()]
    return m[0]["id"] if m else None


def can_fetch(order):
    cls = connectors.REGISTRY.get((order or {}).get("platform") or "")
    return bool(cls and getattr(cls, "LABEL_READY", False) and _shop_id(order))


def save_doc(order, doc, source):
    """接口取到的面单存起来：doc = {"kind": "pdf" | "png", "data": bytes, "tracking_no": ""}。图片转成 PDF 存，统一格式。"""
    os.makedirs(core_labels.LABEL_DIR, exist_ok=True)
    name = f"{order['id']}.pdf"
    path = os.path.join(core_labels.LABEL_DIR, name)
    data = doc.get("data") or b""
    if doc.get("kind") == "png":
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PDF", resolution=300.0)
        data = buf.getvalue()
    if not data.startswith(b"%PDF"):
        raise ValueError("平台返回的面单不是 PDF / 图片")
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    c = db.conn()
    c.execute("UPDATE orders SET label_file=? WHERE id=?", (name, order["id"]))
    if doc.get("tracking_no") and not order.get("tracking_no"):
        c.execute("UPDATE orders SET tracking_no=? WHERE id=?", (doc["tracking_no"], order["id"]))
    from core import orders
    orders.log(order["id"], "系统", "取平台面单", source, commit=False)
    c.commit()
    order["label_file"] = name
    return path


def fetch(order):
    """从平台接口取面单。没接通抛 connectors.NotReady。"""
    from core import integrations
    cls = connectors.REGISTRY.get(order.get("platform") or "")
    if not cls or not getattr(cls, "LABEL_READY", False):
        raise connectors.NotReady(f"{getattr(cls, 'LABEL', order.get('platform'))} 取面单接口还没接通")
    sid = _shop_id(order)
    if not sid:
        raise connectors.NotReady("没有对应的已启用店铺")
    s = integrations.get_shop_raw(sid)
    conn = connectors.make(s["platform"], s["creds"])
    try:
        doc = conn.fetch_label(order)
    finally:
        integrations._store_creds(sid, conn)
    return save_doc(order, doc, f"{cls.LABEL} 接口")


def ensure(order):
    """有面单就用；没有、而且这个平台的接口接通了，就去取。返回 (路径或 None, 说明)。"""
    p = awb_path(order)
    if p:
        return p, ""
    if not can_fetch(order):
        return None, "还没有平台面单（先在订单页上传平台面单 PDF）"
    try:
        return fetch(order), ""
    except Exception as e:  # noqa: BLE001  取不到不影响别的订单
        return None, f"从平台取面单失败：{e}"


def status():
    """面单来源一览（设置页显示）。"""
    out = [{"id": "upload", "zh": "上传平台面单 PDF", "th": "อัปโหลด PDF ใบปะหน้าแพลตฟอร์ม", "ready": True,
            "note_zh": "订单页「上传平台面单」：Shopee / Lazada / TikTok 卖家中心或 BigSeller 批量打印的 PDF，按订单号 / 运单号自动拆到每个订单",
            "note_th": "หน้าออเดอร์「อัปโหลดใบปะหน้า」: PDF จาก Seller Center หรือ BigSeller แยกตามเลขออเดอร์ / เลขพัสดุอัตโนมัติ"}]
    for p in ("shopee", "lazada", "tiktok"):
        cls = connectors.REGISTRY.get(p)
        if not cls:
            continue
        shops = len(_shops(p))
        ready = bool(getattr(cls, "LABEL_READY", False)) and shops > 0
        out.append({"id": p, "zh": f"{cls.LABEL} 接口自动取", "th": f"ดึงจาก API {cls.LABEL}", "ready": ready,
                    "shops": shops, "label_ready": bool(getattr(cls, "LABEL_READY", False)),
                    "note_zh": getattr(cls, "LABEL_NOTE", "") or "未接入", "note_th": getattr(cls, "LABEL_NOTE_TH", "") or "ยังไม่เชื่อมต่อ"})
    out.append({"id": "self", "zh": "自制面单", "th": "ใบปะหน้าทำเอง", "ready": True,
                "note_zh": "手工单、自己找快递：按快递公司的版式（上面「面单模板预览」）",
                "note_th": "ออเดอร์สร้างเอง / ส่งเอง: ใช้แบบของบริษัทขนส่ง"})
    return out
