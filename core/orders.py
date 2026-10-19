"""订单中心：导入（BigSeller / Lazada / Shopee / TikTok 导出的 Excel 或 CSV，任意格式）、SKU 对应产品、备注与定制要求。

导入方式：第一次导入某种表格时，系统自动猜每一列是什么，你在界面上确认/修改后保存为「导入方案」，
以后同样格式的表格自动套用。一行一个商品（同一订单多个商品就是多行，订单号相同）。
"""
import csv
import datetime as dt
import io
import json
import os
import re
import time
import uuid

import openpyxl

from . import db, store
from .config import DATA_DIR

IMPORT_DIR = os.path.join(DATA_DIR, "imports")

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT, shop TEXT, order_no TEXT NOT NULL,
  status TEXT, status_raw TEXT,
  order_time REAL, ship_by REAL,
  buyer TEXT, buyer_note TEXT, seller_note TEXT,
  custom_note TEXT, priority INTEGER DEFAULT 0,
  order_total REAL, shipping_fee REAL, platform_fee REAL,
  tracking_no TEXT, kind TEXT DEFAULT 'normal',
  imported_at REAL, updated_at REAL, raw TEXT,
  UNIQUE(platform, order_no)
);
CREATE INDEX IF NOT EXISTS orders_time ON orders(order_time);
CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL,
  sku TEXT, product_id TEXT, variant_idx INTEGER,
  name TEXT, variation TEXT, qty INTEGER DEFAULT 1, unit_price REAL, item_total REAL,
  color TEXT, material TEXT, grams REAL, hours REAL
);
CREATE INDEX IF NOT EXISTS items_order ON order_items(order_id);
CREATE TABLE IF NOT EXISTS order_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, ts REAL, username TEXT, action TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS order_log_order ON order_log(order_id);
CREATE TABLE IF NOT EXISTS import_profiles (
  name TEXT PRIMARY KEY, mapping TEXT, platform TEXT, signature TEXT, updated_at REAL
);
CREATE TABLE IF NOT EXISTS buyers (
  key TEXT PRIMARY KEY, name TEXT, level TEXT DEFAULT '', note TEXT, updated_at REAL, username TEXT
);
CREATE TABLE IF NOT EXISTS handovers (
  id INTEGER PRIMARY KEY AUTOINCREMENT, carrier TEXT, method TEXT, note TEXT, created_at REAL, username TEXT,
  closed_at REAL, closed_by TEXT
);
"""

# 字段 → 表头里可能出现的词（中文 / 英文 / 泰文，小写匹配，越靠前越优先）
FIELDS = {
    "order_no": ["平台订单号", "订单编号", "订单号", "order number", "order id", "order no", "order_id", "order sn",
                 "หมายเลขคำสั่งซื้อ", "เลขที่คำสั่งซื้อ", "หมายเลขออเดอร์"],
    "platform": ["平台", "platform", "channel", "แพลตฟอร์ม"],
    "shop": ["店铺", "shop", "store", "ร้านค้า", "ชื่อร้าน"],
    "status": ["订单状态", "状态", "order status", "status", "สถานะคำสั่งซื้อ", "สถานะการสั่งซื้อ", "สถานะ"],
    "order_time": ["下单时间", "创建时间", "订单时间", "order creation", "created at", "order date", "create time",
                   "created time", "วันที่ทำการสั่งซื้อ", "วันที่สั่งซื้อ", "เวลาสั่งซื้อ"],
    "ship_by": ["最晚发货", "发货截止", "ship by", "shipping deadline", "ship before", "ต้องจัดส่งภายใน", "กำหนดส่ง"],
    "buyer": ["买家姓名", "买家账号", "买家", "buyer name", "buyer username", "customer name", "username", "ชื่อผู้ซื้อ",
              "ชื่อผู้ใช้"],
    "receiver": ["收件人姓名", "收件人", "收货人", "recipient name", "recipient", "receiver", "shipping name", "ชื่อผู้รับ", "ผู้รับ"],
    "phone": ["收件人电话", "联系电话", "手机号", "电话", "phone number", "phone", "mobile", "เบอร์โทรศัพท์", "เบอร์โทร",
              "หมายเลขโทรศัพท์"],
    "address": ["收件地址", "收货地址", "详细地址", "地址", "shipping address", "delivery address", "address", "ที่อยู่ในการจัดส่ง",
                "ที่อยู่จัดส่ง", "ที่อยู่"],
    "postcode": ["邮编", "邮政编码", "postcode", "postal code", "zip code", "zipcode", "zip", "รหัสไปรษณีย์"],
    "carrier": ["物流公司", "物流方式", "快递公司", "承运商", "shipping provider", "shipping option", "delivery option",
                "carrier", "logistics", "ตัวเลือกการจัดส่ง", "บริษัทขนส่ง", "ขนส่ง"],
    "cod": ["货到付款金额", "代收货款", "cod amount", "cod value", "เก็บเงินปลายทาง"],
    "buyer_note": ["买家留言", "买家备注", "buyer message", "buyer note", "remark from buyer", "note",
                   "หมายเหตุจากผู้ซื้อ", "ข้อความจากผู้ซื้อ"],
    "seller_note": ["卖家备注", "订单备注", "seller note", "seller remark", "หมายเหตุผู้ขาย"],
    "sku": ["商品sku", "seller sku", "sku reference", "sku编号", "平台sku", "sku", "เลขอ้างอิง sku", "รหัส sku"],
    "product_name": ["商品名称", "产品名称", "商品标题", "item name", "product name", "product", "ชื่อสินค้า"],
    "variation": ["规格", "变种", "属性", "variation", "variant", "ตัวเลือกสินค้า", "ชื่อตัวเลือก"],
    "qty": ["数量", "商品数量", "quantity", "qty", "จำนวน"],
    "unit_price": ["单价", "商品单价", "成交价", "unit price", "deal price", "item price", "paid price", "ราคาต่อชิ้น", "ราคาขาย"],
    "item_total": ["商品总价", "商品金额", "小计", "subtotal", "item total", "ราคารวมสินค้า"],
    "order_total": ["订单金额", "订单总额", "实付金额", "order amount", "order total", "total amount", "grand total",
                    "ยอดรวมคำสั่งซื้อ", "ยอดชำระ"],
    "shipping_fee": ["运费", "shipping fee", "shipping cost", "ค่าจัดส่ง"],
    "platform_fee": ["平台费用合计", "平台费用", "手续费", "total fees", "platform fee", "ค่าธรรมเนียมรวม", "ค่าธรรมเนียม"],
    # v2.11 金额拆分（有就导入，用来算真实利润）
    "item_amount": ["商品总额", "商品金额合计", "商品原价合计", "items total", "merchandise subtotal", "ราคาสินค้ารวม"],
    "buyer_shipping": ["买家支付运费", "买家运费", "shipping fee paid by buyer", "buyer paid shipping", "ค่าจัดส่งที่ผู้ซื้อชำระ"],
    "platform_discount": ["平台优惠", "平台补贴", "平台优惠券", "platform voucher", "platform discount", "lazada voucher",
                          "shopee voucher", "โค้ดส่วนลดจาก shopee", "ส่วนลดจากแพลตฟอร์ม"],
    "seller_discount": ["卖家优惠", "店铺优惠", "卖家优惠券", "seller voucher", "shop voucher", "seller discount",
                        "โค้ดส่วนลดของร้านค้า", "ส่วนลดจากร้านค้า"],
    "commission": ["平台佣金", "佣金", "commission fee", "commission", "ค่าคอมมิชชั่น"],
    "service_fee": ["服务费", "service fee", "ค่าบริการ"],
    "payment_fee": ["支付手续费", "交易手续费", "payment fee", "transaction fee", "ค่าธรรมเนียมการชำระเงิน", "ค่าธรรมเนียมธุรกรรม"],
    "settlement": ["结算金额", "预计结算", "实际到账", "回款金额", "payout amount", "settlement amount", "escrow amount",
                   "release amount", "ยอดเงินที่ได้รับ", "ยอดที่ได้รับ"],
    "payment": ["付款方式", "支付方式", "payment method", "วิธีการชำระเงิน"],
    "tracking_no": ["运单号", "物流单号", "tracking number", "tracking no", "เลขพัสดุ", "หมายเลขติดตามพัสดุ"],
}
FIELD_LABELS = {
    "order_no": "订单号（必选）", "platform": "平台", "shop": "店铺", "status": "订单状态", "order_time": "下单时间",
    "ship_by": "最晚发货时间", "buyer": "买家", "buyer_note": "买家留言", "seller_note": "卖家备注",
    "sku": "SKU（必选）", "product_name": "商品名称", "variation": "规格/颜色", "qty": "数量",
    "unit_price": "单价", "item_total": "商品小计", "order_total": "订单金额", "shipping_fee": "运费",
    "platform_fee": "平台费用/佣金", "tracking_no": "运单号",
    "receiver": "收件人", "phone": "收件人电话", "address": "收件地址", "postcode": "邮编", "carrier": "物流公司",
    "cod": "货到付款金额",
    "item_amount": "商品总额", "buyer_shipping": "买家付的运费", "platform_discount": "平台优惠（平台出钱）",
    "seller_discount": "卖家优惠（自己出钱）", "commission": "佣金", "service_fee": "服务费", "payment_fee": "支付手续费",
    "settlement": "结算金额（实际到账）", "payment": "付款方式",
}
MONEY_FIELDS = ("item_amount", "buyer_shipping", "platform_discount", "seller_discount", "commission", "service_fee",
                "payment_fee", "settlement")

# 订单状态归类
STATUS_RULES = [
    # 拒收 / 派送失败 要放在「取消」前面（取消里有 failed）
    ("delivery_failed", ["拒收", "派送失败", "配送失败", "投递失败", "退回卖家", "delivery failed", "failed delivery", "failed_delivery",
                         "delivery_failed", "returned to seller", "package returned", "rejected by buyer", "ปฏิเสธการรับ",
                         "จัดส่งไม่สำเร็จ", "ตีกลับ"]),
    ("cancelled", ["取消", "cancel", "ยกเลิก", "关闭", "closed", "失败", "failed"]),
    ("returned", ["退货", "退款", "return", "refund", "คืน"]),
    ("completed", ["已完成", "完成", "已签收", "complete", "delivered", "สำเร็จ", "จัดส่งสำเร็จ", "ได้รับสินค้า"]),
    ("shipped", ["已发货", "运输中", "shipped", "shipping", "in transit", "in_transit", "awaiting_collection", "จัดส่งแล้ว", "กำลังจัดส่ง"]),
    ("unpaid", ["未付款", "待付款", "unpaid", "pending payment", "ยังไม่ชำระ", "รอชำระ"]),
    ("to_ship", ["待发货", "待处理", "待打单", "已付款", "awaiting_shipment", "awaiting shipment", "to ship", "ready to ship", "pending", "packed", "processing",
                 "ที่ต้องจัดส่ง", "รอจัดส่ง", "เตรียมจัดส่ง"]),
]
STATUS_ZH = {"unpaid": "未付款", "to_ship": "待发货", "shipped": "已发货", "completed": "已完成",
             "cancelled": "已取消", "returned": "退货/退款", "delivery_failed": "拒收/派送失败", "quote": "报价/预订单",
             "other": "其他"}
SHIP_METHOD_ZH = {"pickup": "上门揽收", "dropoff": "送到网点", "self": "自己送 / 其他"}
LEVEL_ZH = {"": "普通", "vip": "VIP", "wholesale": "批发客户", "watch": "需留意", "blacklist": "黑名单"}
ACTIVE_STATUSES = ("to_ship", "quote")
KIND_ZH = {"normal": "平台订单", "manual": "私下成交", "wholesale": "批发/大单", "custom": "定制单", "quote": "报价"}   # 需要生产的状态


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(orders)")}
    if "source" not in cols:   # 订单从哪来：file 表格 / manual 手工 / api 接口 / lazada 等店铺对接
        c.execute("ALTER TABLE orders ADD COLUMN source TEXT")
    if "tags" not in cols:     # 标签，逗号分隔
        c.execute("ALTER TABLE orders ADD COLUMN tags TEXT")
    if "shipped_at" not in cols:
        c.execute("ALTER TABLE orders ADD COLUMN shipped_at REAL")
    for col, typ in (("receiver", "TEXT"), ("phone", "TEXT"), ("address", "TEXT"), ("postcode", "TEXT"), ("carrier", "TEXT"),
                     ("cod", "REAL"), ("label_file", "TEXT"), ("label_printed_at", "REAL"),
                     # v2.11：审单挂起、买家、付款方式、发货方式、交接单、金额拆分
                     ("hold", "INTEGER DEFAULT 0"), ("hold_reason", "TEXT"), ("reviewed_at", "REAL"), ("reviewed_by", "TEXT"),
                     ("buyer_key", "TEXT"), ("payment", "TEXT"), ("ship_method", "TEXT"), ("handover_id", "INTEGER"),
                     ("pack_box", "TEXT"),          # v2.35：打包用的纸箱（空 = 按产品自动选；none = 不用纸箱）
                     *((k, "REAL") for k in MONEY_FIELDS)):
        if col not in cols:
            c.execute(f"ALTER TABLE orders ADD COLUMN {col} {typ}")
    c.execute("CREATE INDEX IF NOT EXISTS orders_buyer ON orders(buyer_key)")
    for r in c.execute("SELECT id, platform, buyer, phone FROM orders WHERE buyer_key IS NULL").fetchall():
        c.execute("UPDATE orders SET buyer_key=? WHERE id=?", (buyer_key_of(r["platform"], r["buyer"], r["phone"]), r["id"]))
    c.commit()


def buyer_key_of(platform, buyer, phone):
    """同一个买家：有电话按电话（后 9 位，平台之间也能对上），没有电话按 平台+买家名。"""
    d = re.sub(r"\D", "", str(phone or ""))
    if len(d) >= 9 and not set(d[-9:]) <= {"0", "*"}:
        return "p:" + d[-9:]
    b = str(buyer or "").strip().lower()
    return f"b:{(platform or '').lower()}:{b}" if b else ""


def is_cod(o):
    pay = str(o.get("payment") or "").lower()
    return bool((o.get("cod") or 0) > 0 or pay == "cod" or any(w in pay for w in ("cod", "货到付款", "เก็บเงินปลายทาง", "cash on delivery")))


def norm_status(raw):
    s = str(raw or "").strip().lower()
    if not s:
        return "to_ship"
    for st, words in STATUS_RULES:
        if any(w in s for w in words):
            return st
    return "other"


def guess_platform(text):
    t = str(text or "").lower()
    for p in ("lazada", "shopee", "tiktok"):
        if p in t:
            return p
    if "虾皮" in t:
        return "shopee"
    return ""


# ---------------- 读表格 ----------------
def _read_rows(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".txt"):
        raw = open(path, "rb").read()
        for enc in ("utf-8-sig", "gbk", "cp874", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        return [r for r in csv.reader(io.StringIO(text))]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    best = None
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if best is None or len(rows) > len(best):
            best = rows
    return best or []


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, dt.datetime) else v.strftime("%Y-%m-%d")
    return str(v).strip()


def _score_header(row):
    cells = [_cell(c).lower() for c in row]
    hits = 0
    for words in FIELDS.values():
        if any(any(w in c for w in words) for c in cells if c):
            hits += 1
    return hits


def find_header(rows):
    best, idx = -1, 0
    for i, r in enumerate(rows[:15]):
        s = _score_header(r)
        if s > best:
            best, idx = s, i
    return idx


def auto_map(headers):
    """{列序号: 字段}；每个字段只用一次，优先匹配更长、更具体的词。"""
    cand = []
    for ci, h in enumerate(headers):
        hl = h.lower().strip()
        if not hl:
            continue
        for field, words in FIELDS.items():
            for rank, w in enumerate(words):
                if w == hl:
                    cand.append((0, -len(w), rank, ci, field))
                elif w in hl:
                    cand.append((1, -len(w), rank, ci, field))
    cand.sort()
    used_c, used_f, out = set(), set(), {}
    for _a, _b, _r, ci, field in cand:
        if ci in used_c or field in used_f:
            continue
        out[str(ci)] = field
        used_c.add(ci)
        used_f.add(field)
    return out


def signature(headers):
    return "|".join(h.strip().lower() for h in headers if h.strip())[:500]


def preview(file_storage):
    os.makedirs(IMPORT_DIR, exist_ok=True)
    ext = os.path.splitext(file_storage.filename or "")[1].lower() or ".xlsx"
    if ext not in (".xlsx", ".xlsm", ".csv", ".txt"):
        raise ValueError("请上传 .xlsx 或 .csv 表格（旧的 .xls 请先用 Excel 另存为 .xlsx）")
    token = uuid.uuid4().hex[:12]
    path = os.path.join(IMPORT_DIR, token + ext)
    file_storage.save(path)
    rows = _read_rows(path)
    if not rows:
        raise ValueError("表格是空的")
    hi = find_header(rows)
    headers = [_cell(c) for c in rows[hi]]
    data = [[_cell(c) for c in r] for r in rows[hi + 1:] if any(_cell(c) for c in r)]
    sig = signature(headers)
    prof = None
    for r in db.conn().execute("SELECT * FROM import_profiles"):
        if r["signature"] == sig:
            prof = {"name": r["name"], "mapping": json.loads(r["mapping"]), "platform": r["platform"]}
            break
    mapping = prof["mapping"] if prof else auto_map(headers)
    platform = (prof or {}).get("platform") or guess_platform(file_storage.filename) or \
        guess_platform(" ".join(headers))
    json.dump({"path": path, "header_row": hi, "filename": file_storage.filename},
              open(os.path.join(IMPORT_DIR, token + ".json"), "w", encoding="utf-8"))
    return {"token": token, "headers": headers, "sample": data[:8], "rows": len(data), "mapping": mapping,
            "profile": prof["name"] if prof else "", "platform": platform,
            "fields": FIELD_LABELS, "profiles": [r["name"] for r in db.conn().execute("SELECT name FROM import_profiles")]}


# ---------------- 解析数值/时间 ----------------
def _num(s):
    s = str(s or "").replace(",", "").replace("฿", "").replace("THB", "").replace("¥", "").strip()
    m = re.search(r"-?\d+(\.\d+)?", s)
    return float(m.group(0)) if m else None


def _time(s):
    s = str(s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{10}(\.\d+)?", s):
        return float(s)
    if re.fullmatch(r"\d{13}", s):       # 毫秒
        return float(s) / 1000
    if re.fullmatch(r"\d{5}(\.\d+)?", s):   # Excel 序列日期
        return (dt.datetime(1899, 12, 30) + dt.timedelta(days=float(s))).timestamp()
    try:      # ISO 格式，带时区，例如 2026-10-05T10:00:00+07:00
        if re.match(r"\d{4}-\d{2}-\d{2}T", s):
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            return d.timestamp()
    except ValueError:
        pass
    s2 = re.sub(r"\s+", " ", s.replace("/", "-").replace("T", " ")).split(".")[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
                "%d-%m-%Y", "%d %b %Y %H:%M", "%d %b %Y", "%d %B %Y"):
        try:
            d = dt.datetime.strptime(s2, fmt)
        except ValueError:
            continue
        if d.year > 2400:   # 泰国佛历
            d = d.replace(year=d.year - 543)
        return d.timestamp()
    return None


# ---------------- SKU → 产品 ----------------
def sku_index():
    idx = {}
    for item in store.list_products():
        p = store.load(item["id"])
        for i, v in enumerate(p.get("variants", [])):
            if v.get("sku"):
                idx[v["sku"].strip().upper()] = (p["id"], i)
    return idx


def match_sku(sku, idx):
    s = (sku or "").strip().upper()
    if not s:
        return None
    if s in idx:
        return idx[s]
    # 去掉平台加的前后缀再试（例如 "3DP0001-WH-01"、"SKU:3DP0001-WH"）
    m = re.search(r"[A-Z]{1,6}\d{3,5}(-[A-Z0-9]{1,6}){0,2}", s)
    if m:
        k = m.group(0)
        while k:
            if k in idx:
                return idx[k]
            if "-" not in k:
                break
            k = k.rsplit("-", 1)[0]
    return None


def _variant_info(pid, vi):
    try:
        p = store.load(pid)
        v = p["variants"][vi]
        return {"color": v.get("opt1_zh", ""), "material": p.get("material") or "PLA",
                "grams": v.get("grams"), "hours": v.get("hours"), "name": p.get("name_zh", "")}
    except (FileNotFoundError, IndexError, KeyError):
        return {}


# ---------------- 导入 ----------------
def commit(token, mapping, platform="", profile_name="", user=""):
    """表格导入：把每一行转成标准订单格式，再交给 upsert（和 API 自动导入走同一条路）。"""
    meta_path = os.path.join(IMPORT_DIR, token + ".json")
    if not os.path.exists(meta_path):
        raise ValueError("导入已过期，请重新选择文件")
    meta = json.load(open(meta_path, encoding="utf-8"))
    rows = _read_rows(meta["path"])
    hi = meta["header_row"]
    headers = [_cell(c) for c in rows[hi]]
    data = [[_cell(c) for c in r] for r in rows[hi + 1:] if any(_cell(c) for c in r)]
    fmap = {f: int(ci) for ci, f in mapping.items() if f}
    if "order_no" not in fmap:
        raise ValueError("请指定哪一列是「订单号」")
    if "sku" not in fmap:
        raise ValueError("请指定哪一列是「SKU」")
    c = db.conn()
    if profile_name:
        # 同样的表头只留一个格式；名字和别的格式重复时自动加编号
        sig = signature(headers)
        c.execute("DELETE FROM import_profiles WHERE signature=?", (sig,))
        name, k = profile_name.strip()[:40], 2
        while c.execute("SELECT 1 FROM import_profiles WHERE name=?", (name,)).fetchone():
            name = f"{profile_name.strip()[:36]} ({k})"; k += 1
        c.execute("INSERT INTO import_profiles(name, mapping, platform, signature, updated_at) VALUES(?,?,?,?,?)",
                  (name, json.dumps(mapping), platform, sig, time.time()))
        c.commit()
    groups = {}
    for r in data:
        def g(f, r=r):
            i = fmap.get(f)
            return r[i] if i is not None and i < len(r) else ""
        no = g("order_no").strip()
        if not no:
            continue
        groups.setdefault(no, []).append(g)
    orders = []
    for no, getters in groups.items():
        g0 = getters[0]
        o = {k: g0(k) for k in ORDER_FIELDS if k != "order_no"}
        o["order_no"] = no
        o["items"] = [{"sku": g("sku"), "name": g("product_name"), "variation": g("variation"), "qty": g("qty"),
                       "unit_price": g("unit_price"), "item_total": g("item_total")} for g in getters]
        orders.append(o)
    stats = upsert(orders, source="file", default_platform=platform, user=user, audit=False)
    db.audit(user, "导入订单", "", f"{meta.get('filename')}: 新 {stats['orders_new']}，更新 {stats['orders_updated']}")
    return stats


# 标准订单格式（API / 店铺对接 / 表格导入共用）
ORDER_FIELDS = ("platform", "shop", "order_no", "status", "order_time", "ship_by", "buyer", "buyer_note", "seller_note",
                "order_total", "shipping_fee", "platform_fee", "tracking_no", "receiver", "phone", "address", "postcode",
                "carrier", "cod", "payment", "ship_method") + MONEY_FIELDS


def _status_of(v):
    s = str(v or "").strip()
    return s if s in STATUS_ZH else norm_status(s)


def upsert(orders, source="api", default_platform="", user="", audit=True):
    """新增或更新订单。orders: [{platform, order_no, status, order_time, ..., items:[{sku, qty, unit_price, ...}]}]
    - 平台 + 订单号 相同就是同一个订单：更新状态等信息，不覆盖内部的定制备注/加急。
    - 已经开始生产的订单，商品明细不再改动。
    - 时间可以是 Unix 秒数、毫秒数或 "2026-10-05 10:00" 这类文字（支持泰国佛历）。"""
    if not isinstance(orders, list):
        raise ValueError("orders 必须是列表")
    c = db.conn()
    idx = sku_index()
    now = time.time()
    stats = {"orders_new": 0, "orders_updated": 0, "items": 0, "unmatched": {}, "skipped_items_locked": 0,
             "errors": []}
    new_ids, status_changed = [], []
    for n, o in enumerate(orders):
        if not isinstance(o, dict):
            stats["errors"].append(f"第 {n + 1} 个订单格式不对"); continue
        no = str(o.get("order_no") or "").strip()
        if not no:
            stats["errors"].append(f"第 {n + 1} 个订单缺少 order_no"); continue
        plat = (guess_platform(o.get("platform")) or default_platform or str(o.get("platform") or "") or "other").lower()
        status_raw = str(o.get("status") or "")
        fields = {
            "platform": plat, "shop": str(o.get("shop") or ""), "order_no": no, "status": _status_of(status_raw),
            "status_raw": status_raw, "order_time": _time(o.get("order_time")) or now, "ship_by": _time(o.get("ship_by")),
            "buyer": str(o.get("buyer") or ""), "buyer_note": str(o.get("buyer_note") or ""),
            "seller_note": str(o.get("seller_note") or ""), "order_total": _num(o.get("order_total")),
            "shipping_fee": _num(o.get("shipping_fee")), "platform_fee": _num(o.get("platform_fee")),
            "tracking_no": str(o.get("tracking_no") or ""), "source": source,
            "receiver": str(o.get("receiver") or ""), "phone": str(o.get("phone") or ""),
            "address": str(o.get("address") or ""), "postcode": str(o.get("postcode") or ""),
            "carrier": str(o.get("carrier") or ""), "cod": _num(o.get("cod")),
            "payment": _payment(o), "ship_method": str(o.get("ship_method") or "") if o.get("ship_method") in SHIP_METHOD_ZH else "",
            **{k: _num(o.get(k)) for k in MONEY_FIELDS},
        }
        if o.get("raw") is not None:
            fields["raw"] = json.dumps(o["raw"], ensure_ascii=False)[:20000]
        items = o.get("items")
        old = c.execute("SELECT * FROM orders WHERE platform=? AND order_no=?", (plat, no)).fetchone()
        if old:
            sets = {k: v for k, v in fields.items() if k not in ("platform", "order_no", "source") and v not in (None, "")}
            if not o.get("order_time"):
                sets.pop("order_time", None)
            if not status_raw:
                sets.pop("status", None)
            sets["updated_at"] = now
            c.execute(f"UPDATE orders SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), old["id"]))
            oid = old["id"]
            stats["orders_updated"] += 1
            if sets.get("status") and sets["status"] != old["status"]:
                log(oid, user or source, f"状态 {STATUS_ZH.get(old['status'], old['status'])} → "
                                         f"{STATUS_ZH.get(sets['status'], sets['status'])}", f"来源：{source}", commit=False)
            if sets.get("tracking_no") and sets["tracking_no"] != (old["tracking_no"] or ""):
                log(oid, user or source, "运单号", sets["tracking_no"], commit=False)
            if "buyer" in sets or "phone" in sets:
                c.execute("UPDATE orders SET buyer_key=? WHERE id=?",
                          (buyer_key_of(plat, sets.get("buyer", old["buyer"]), sets.get("phone", old["phone"])), oid))
            if sets.get("status") and sets["status"] != old["status"]:
                status_changed.append((oid, old["status"], sets["status"]))
            if items is None:          # 只更新状态（例如平台推送「已发货」）
                continue
            locked = c.execute("SELECT COUNT(*) FROM jobs WHERE order_id=? AND (status!='todo' OR COALESCE(qty_done,0)>0 "
                               "OR run_id IS NOT NULL)",
                               (oid,)).fetchone()[0] \
                if _has_jobs_table(c) else 0
            if locked:
                stats["skipped_items_locked"] += 1
                continue
            if _has_jobs_table(c):   # 还没开始打印的任务按新明细重新生成
                c.execute("DELETE FROM jobs WHERE order_id=? AND status='todo'", (oid,))
            c.execute("DELETE FROM order_items WHERE order_id=?", (oid,))
        else:
            fields.update(imported_at=now, updated_at=now)
            cur = c.execute(f"INSERT INTO orders({', '.join(fields)}) VALUES({', '.join('?' * len(fields))})",
                            tuple(fields.values()))
            oid = cur.lastrowid
            c.execute("UPDATE orders SET buyer_key=? WHERE id=?", (buyer_key_of(plat, fields["buyer"], fields["phone"]), oid))
            new_ids.append(oid)
            stats["orders_new"] += 1
            log(oid, user or source, "新订单", f"来源：{source}，状态 {STATUS_ZH.get(fields['status'], fields['status'])}",
                commit=False)
        for it in items or []:
            sku = str(it.get("sku") or "").strip()
            hit = match_sku(sku, idx)
            info = _variant_info(*hit) if hit else {}
            if not hit and sku:
                stats["unmatched"][sku] = stats["unmatched"].get(sku, 0) + 1
            qty = int(_num(it.get("qty")) or 1)
            unit = _num(it.get("unit_price"))
            total = _num(it.get("item_total")) or (unit * qty if unit is not None else None)
            c.execute("""INSERT INTO order_items(order_id, sku, product_id, variant_idx, name, variation, qty, unit_price,
                         item_total, color, material, grams, hours) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (oid, sku, hit[0] if hit else None, hit[1] if hit else None,
                       str(it.get("name") or "") or info.get("name", ""), str(it.get("variation") or ""), qty, unit, total,
                       info.get("color", ""), info.get("material", ""), info.get("grams"), info.get("hours")))
            stats["items"] += 1
        _auto_ship_by(c, oid)
        _ship_defaults(c, oid)
    c.commit()
    # 新订单自动审单；变成待发货（例如付款了）也审一次；拒收自动登记售后
    held = 0
    for oid in new_ids + [x[0] for x in status_changed if x[2] == "to_ship"]:
        held += 1 if auto_review(oid) else 0
    for oid, _o, new in status_changed:
        on_status_change(oid, new, user or source, _o)
    for oid in new_ids:
        r = c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()
        if r and r["status"] == "delivery_failed":
            on_status_change(oid, "delivery_failed", user or source)
    stats["held"] = held
    if audit and (stats["orders_new"] or stats["orders_updated"]):
        db.audit(user or source, "自动导入订单", "", f"{source}: 新 {stats['orders_new']}，更新 {stats['orders_updated']}")
    stats["unmatched"] = [{"sku": k, "rows": v} for k, v in stats["unmatched"].items()]
    return stats


def _auto_ship_by(c, oid):
    """表格里没有最晚发货时间：按商品的「发货天数」推算（没填用设置里的默认天数）。"""
    o = c.execute("SELECT ship_by, order_time, status FROM orders WHERE id=?", (oid,)).fetchone()
    if not o or o["ship_by"] or o["status"] not in ("to_ship", "quote"):
        return
    from .config import load_config
    cfg = load_config()
    days = []
    for r in c.execute("SELECT DISTINCT product_id FROM order_items WHERE order_id=? AND product_id IS NOT NULL", (oid,)):
        try:
            d = store.load(r["product_id"]).get("lead_days")
            if d not in (None, ""):
                days.append(float(d))
        except FileNotFoundError:
            pass
    n = max(days) if days else float(cfg.get("default_ship_days") or 3)
    c.execute("UPDATE orders SET ship_by=? WHERE id=?", ((o["order_time"] or time.time()) + n * 86400, oid))


def _payment(o):
    raw = str(o.get("payment") or "").strip()
    if is_cod({"payment": raw, "cod": _num(o.get("cod"))}):
        return "cod"
    return raw[:40]


def _ship_defaults(c, oid):
    """平台物流：没填物流公司时按平台默认（Lazada → LEX 等），没填发货方式按设置（上门揽收 / 送到网点）。"""
    o = c.execute("SELECT platform, carrier, ship_method FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        return
    from .config import load_config
    cfg = load_config()
    sets = {}
    if not o["carrier"]:
        dflt = (cfg.get("carrier_" + (o["platform"] or "")) or "").strip()
        if dflt:
            sets["carrier"] = dflt
    if not o["ship_method"] and o["platform"] in ("lazada", "shopee", "tiktok"):
        m = cfg.get("ship_method_default") or "pickup"
        if m in SHIP_METHOD_ZH:
            sets["ship_method"] = m
    if sets:
        c.execute(f"UPDATE orders SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), oid))


def _has_jobs_table(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone())


def rematch():
    """产品 SKU 改过/新建后，重新给没对上的订单商品找产品。"""
    c = db.conn()
    idx = sku_index()
    n = 0
    for r in c.execute("SELECT id, sku FROM order_items WHERE product_id IS NULL").fetchall():
        hit = match_sku(r["sku"], idx)
        if hit:
            info = _variant_info(*hit)
            c.execute("UPDATE order_items SET product_id=?, variant_idx=?, color=?, material=?, grams=?, hours=? WHERE id=?",
                      (hit[0], hit[1], info.get("color"), info.get("material"), info.get("grams"), info.get("hours"), r["id"]))
            n += 1
    c.commit()
    return n


# ---------------- 查询 / 修改 ----------------
def _order_dict(r, items=None):
    d = dict(r)
    d.pop("raw", None)
    d["status_zh"] = STATUS_ZH.get(d.get("status"), d.get("status"))
    if items is not None:
        d["items"] = items
    return d


def list_orders(status=None, q="", days=60, limit=500):
    c = db.conn()
    conds, args = [], []
    if status:
        if status == "active":
            conds.append(f"status IN ({','.join('?' * len(ACTIVE_STATUSES))})"); args += ACTIVE_STATUSES
        else:
            conds.append("status=?"); args.append(status)
    if days:
        conds.append("order_time>=?"); args.append(time.time() - int(days) * 86400)
    if q:
        conds.append("(order_no LIKE ? OR buyer LIKE ? OR id IN (SELECT order_id FROM order_items WHERE sku LIKE ? OR name LIKE ?))")
        args += [f"%{q}%"] * 4
    sql = "SELECT * FROM orders" + (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY order_time DESC LIMIT ?"
    args.append(int(limit))
    rows = c.execute(sql, args).fetchall()
    ids = [r["id"] for r in rows]
    items = {}
    if ids:
        for it in c.execute(f"SELECT * FROM order_items WHERE order_id IN ({','.join('?' * len(ids))})", ids):
            items.setdefault(it["order_id"], []).append(dict(it))
    return [_order_dict(r, items.get(r["id"], [])) for r in rows]


def get_order(oid):
    c = db.conn()
    r = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not r:
        return None
    items = [dict(i) for i in c.execute("SELECT * FROM order_items WHERE order_id=?", (oid,))]
    return _order_dict(r, items)


FIELD_ZH = {"custom_note": "定制备注", "seller_note": "卖家备注", "priority": "加急", "status": "状态", "ship_by": "最晚发货",
            "kind": "类型", "tracking_no": "运单号", "tags": "标签", "buyer": "买家", "receiver": "收件人",
            "phone": "电话", "address": "地址", "postcode": "邮编", "carrier": "物流", "cod": "货到付款",
            "ship_method": "发货方式", "payment": "付款方式", **{k: FIELD_LABELS[k] for k in MONEY_FIELDS}}


def log(order_id, user, action, detail="", commit=True):
    if not order_id:
        return
    c = db.conn()
    c.execute("INSERT INTO order_log(order_id, ts, username, action, detail) VALUES(?,?,?,?,?)",
              (order_id, time.time(), user or "", action, (detail or "")[:500]))
    if commit:
        c.commit()


def get_log(order_id):
    return [dict(r) for r in db.conn().execute("SELECT * FROM order_log WHERE order_id=? ORDER BY id DESC", (order_id,))]


def update_order(oid, user="", **kw):
    allowed = ("custom_note", "seller_note", "priority", "status", "ship_by", "kind", "tracking_no", "tags", "buyer",
               "receiver", "phone", "address", "postcode", "carrier", "cod", "ship_method", "payment") + MONEY_FIELDS
    sets = {k: v for k, v in kw.items() if k in allowed and v is not None}
    if "ship_method" in sets and sets["ship_method"] not in SHIP_METHOD_ZH and sets["ship_method"] != "":
        raise ValueError("发货方式不对")
    if "status" in sets and sets["status"] not in STATUS_ZH:
        raise ValueError("订单状态不对")
    for k in MONEY_FIELDS:
        if k in sets:
            sets[k] = _num(sets[k]) if sets[k] != "" else None
    if "ship_by" in sets:
        sets["ship_by"] = _time(sets["ship_by"]) if sets["ship_by"] != "" else None
    if "cod" in sets:
        sets["cod"] = _num(sets["cod"])
        if sets["cod"] is None:
            sets.pop("cod")
    if "tags" in sets:
        sets["tags"] = ",".join(dict.fromkeys(t.strip() for t in str(sets["tags"]).replace("，", ",").split(",") if t.strip()))
    c = db.conn()
    old = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not old:
        raise ValueError("订单不存在")
    def _same(k, v):
        ov = old[k]
        if v is None or ov is None:
            return ("" if v is None else str(v)) == ("" if ov is None else str(ov))
        if isinstance(ov, (int, float)) and not isinstance(v, str):
            return float(v) == float(ov)
        return str(v if v is not None else "") == str(ov if ov is not None else "")
    sets = {k: v for k, v in sets.items() if not _same(k, v)}
    if not sets:
        return get_order(oid)
    now = time.time()
    if sets.get("status") in ("shipped", "completed") and not old["shipped_at"]:
        sets["shipped_at"] = now
    sets["updated_at"] = now
    c.execute(f"UPDATE orders SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), oid))
    for k, v in sets.items():
        if k in ("updated_at", "shipped_at"):
            continue
        if k == "status":
            log(oid, user, "状态", f"{STATUS_ZH.get(old['status'], old['status'])} → {STATUS_ZH.get(v, v)}", commit=False)
        elif k == "priority":
            log(oid, user, "加急" if int(v or 0) else "取消加急", "", commit=False)
        else:
            log(oid, user, FIELD_ZH.get(k, k), str(v if v is not None else "（空）")[:200], commit=False)
    if "buyer" in sets or "phone" in sets:
        c.execute("UPDATE orders SET buyer_key=? WHERE id=?",
                  (buyer_key_of(old["platform"], sets.get("buyer", old["buyer"]), sets.get("phone", old["phone"])), oid))
    c.commit()
    if sets.get("status") and sets["status"] != old["status"]:
        on_status_change(oid, sets["status"], user, old["status"])
    return get_order(oid)


# ---------------- ERP 订单列表：分栏、筛选、分页、异常 ----------------
TABS = [("all", "全部"), ("review", "待审核"), ("waiting", "待生产"), ("producing", "生产中"), ("ready", "待发货"),
        ("urgent", "即将超时"), ("shipped", "已发货"), ("completed", "已完成"), ("unpaid", "未付款"), ("quote", "报价"),
        ("cancelled", "已取消"), ("returned", "退货退款"), ("delivery_failed", "拒收/派送失败"), ("exception", "异常")]
URGENT_HOURS = 24


def _stage(o, jc):
    """订单的生产进度：none 没有任务 / waiting 都没开始 / producing 生产中 / ready 都打包好了 / out 都发了"""
    jc = {k: v for k, v in jc.items() if not k.startswith("_")} | {"_plates": jc.get("_plates", 0)}
    n = sum(v for k, v in jc.items() if not k.startswith("_"))
    if not n:
        return "none"
    if jc.get("done", 0) == n:
        return "out"
    if jc.get("packed", 0) + jc.get("done", 0) == n:
        return "ready"
    if jc.get("todo", 0) == n and not jc.get("_plates", 0):
        return "waiting"
    return "producing"


def exceptions(o, jc, now=None):
    now = now or time.time()
    out = []
    if o["status"] not in ("to_ship", "quote"):
        return out
    items = o.get("items") or []
    if any(not i.get("product_id") for i in items):
        out.append("SKU 没对上产品")
    elif any(not i.get("grams") for i in items):
        out.append("产品缺克数（没切片）")
    if not items:
        out.append("没有商品")
    st = o.get("stage")
    if o.get("ship_by") and st not in ("ready", "out"):
        if o["ship_by"] < now:
            out.append("已超过最晚发货时间")
        elif o["ship_by"] < now + 12 * 3600:
            out.append("12 小时内要发货")
    if o.get("_plan_late"):
        out.append("排产来不及")
    if jc.get("_alert"):
        out.append("打印机报警")
    if jc.get("_fails"):
        out.append(f"打印失败 {jc['_fails']} 次")
    return out


def _tab_of(o):
    st, s = o["status"], o.get("stage")
    if st == "to_ship":
        if o.get("hold"):
            return "review"
        if s == "ready":
            return "ready"
        if s == "producing":
            return "producing"
        return "waiting"
    return {"shipped": "shipped", "completed": "completed", "unpaid": "unpaid", "quote": "quote",
            "cancelled": "cancelled", "returned": "returned", "delivery_failed": "delivery_failed"}.get(st, "all")


def is_urgent(o, now=None):
    """即将超时：待发货、还没打包好，最晚发货时间在 24 小时内（含已经超时的）。"""
    now = now or time.time()
    return bool(o["status"] == "to_ship" and o.get("ship_by") and o.get("stage") not in ("ready", "out")
                and o["ship_by"] < now + URGENT_HOURS * 3600)


def search(f):
    """f: tab, q, platform, shop, kind, tag, date_from, date_to, sort, page, page_size"""
    c = db.conn()
    conds, args = [], []
    if f.get("platform"):
        conds.append("platform=?"); args.append(f["platform"])
    if f.get("shop"):
        conds.append("shop=?"); args.append(f["shop"])
    if f.get("kind"):
        conds.append("kind=?"); args.append(f["kind"])
    if f.get("label") == "none":
        conds.append("COALESCE(label_printed_at,0)=0")
    elif f.get("label") == "printed":
        conds.append("label_printed_at>0")
    if f.get("tag"):
        conds.append("(','||COALESCE(tags,'')||',') LIKE ?"); args.append(f"%,{f['tag']},%")
    if f.get("pay") == "cod":
        conds.append("(COALESCE(cod,0)>0 OR payment='cod')")
    elif f.get("pay") == "prepaid":
        conds.append("NOT (COALESCE(cod,0)>0 OR payment='cod')")
    if f.get("carrier"):
        conds.append("carrier=?"); args.append(f["carrier"])
    if f.get("buyer_key"):
        conds.append("buyer_key=?"); args.append(f["buyer_key"])
    if f.get("date_from"):
        t = _time(f["date_from"])
        if t:
            conds.append("order_time>=?"); args.append(t)
    if f.get("date_to"):
        t = _time(f["date_to"])
        if t:
            conds.append("order_time<?"); args.append(t + 86400)
    if f.get("q"):
        q = f"%{f['q'].strip()}%"
        conds.append("(order_no LIKE ? OR buyer LIKE ? OR tracking_no LIKE ? OR custom_note LIKE ? OR buyer_note LIKE ? "
                     "OR receiver LIKE ? OR phone LIKE ? "
                     "OR id IN (SELECT order_id FROM order_items WHERE sku LIKE ? OR name LIKE ?))")
        args += [q] * 9
    rows = c.execute("SELECT * FROM orders" + (" WHERE " + " AND ".join(conds) if conds else ""), args).fetchall()
    ids = [r["id"] for r in rows]
    items, jcs = {}, {}
    if ids:
        ph = ",".join("?" * len(ids))
        for it in c.execute(f"SELECT * FROM order_items WHERE order_id IN ({ph})", ids):
            items.setdefault(it["order_id"], []).append(dict(it))
        if _has_jobs_table(c):
            for j in c.execute(f"SELECT order_id, status, COALESCE(qty_done,0) AS pd, fails, alert, planned_end "
                               f"FROM jobs WHERE order_id IN ({ph})", ids):
                d = jcs.setdefault(j["order_id"], {})
                d[j["status"]] = d.get(j["status"], 0) + 1
                d["_plates"] = d.get("_plates", 0) + j["pd"]
                d["_fails"] = d.get("_fails", 0) + (j["fails"] or 0)
                if j["alert"]:
                    d["_alert"] = 1
                if j["status"] in ("todo", "printing"):
                    d["_end"] = max(d.get("_end", 0), j["planned_end"] or 0)
    now = time.time()
    # 买家：下单次数、拒收次数、分类（列表上显示风险标签）
    bstat, levels = {}, {}
    keys = list({r["buyer_key"] for r in rows if r["buyer_key"]})
    for i in range(0, len(keys), 500):
        part = keys[i:i + 500]
        ph = ",".join("?" * len(part))
        for b in c.execute(f"SELECT buyer_key, COUNT(*) n, SUM(status='delivery_failed') rf FROM orders WHERE buyer_key IN ({ph}) "
                           f"GROUP BY buyer_key", part):
            bstat[b["buyer_key"]] = (b["n"], b["rf"] or 0)
        for b in c.execute(f"SELECT key, level FROM buyers WHERE key IN ({ph})", part):
            levels[b["key"]] = b["level"] or ""
    out = []
    for r in rows:
        o = _order_dict(r, items.get(r["id"], []))
        n, rf = bstat.get(r["buyer_key"], (0, 0))
        o["buyer_tags"] = buyer_risk({"level": levels.get(r["buyer_key"], ""), "refused": rf, "orders": n}) if r["buyer_key"] else []
        o["is_cod"] = is_cod(o)
        jc = jcs.get(r["id"], {})
        o["job_counts"] = {k: v for k, v in jc.items() if not k.startswith("_")}
        o["stage"] = _stage(o, jc)
        o["_plan_late"] = bool(o.get("ship_by") and jc.get("_end") and jc["_end"] > o["ship_by"])
        o["planned_done"] = jc.get("_end") or None
        o["exceptions"] = exceptions(o, jc, now)
        o["tab"] = _tab_of(o)
        o.pop("_plan_late", None)
        out.append(o)
    counts = {k: 0 for k, _ in TABS}
    for o in out:
        counts["all"] += 1
        counts[o["tab"]] = counts.get(o["tab"], 0) + 1
        if o["exceptions"]:
            counts["exception"] += 1
        if is_urgent(o, now):
            counts["urgent"] += 1
    tab = f.get("tab") or "all"
    if tab == "exception":
        out = [o for o in out if o["exceptions"]]
    elif tab == "urgent":
        out = [o for o in out if is_urgent(o, now)]
    elif tab != "all":
        out = [o for o in out if o["tab"] == tab]
    sort = f.get("sort") or "time_desc"
    keyf = {"time_desc": lambda o: -(o["order_time"] or 0), "time_asc": lambda o: o["order_time"] or 0,
            "ship_by": lambda o: o["ship_by"] or 9e12, "amount": lambda o: -(o.get("order_total") or 0)}.get(sort)
    out.sort(key=keyf or (lambda o: -(o["order_time"] or 0)))
    size = max(10, min(500, int(f.get("page_size") or 50)))
    page = max(1, int(f.get("page") or 1))
    total = len(out)
    shops = [r[0] for r in c.execute("SELECT DISTINCT shop FROM orders WHERE COALESCE(shop,'')!='' ORDER BY shop")]
    tags = sorted({t for r in c.execute("SELECT tags FROM orders WHERE COALESCE(tags,'')!=''") for t in r[0].split(",") if t})
    carriers = [r[0] for r in c.execute("SELECT DISTINCT carrier FROM orders WHERE COALESCE(carrier,'')!='' ORDER BY carrier")]
    return {"orders": out[(page - 1) * size: page * size], "total": total, "page": page, "page_size": size,
            "counts": counts, "tabs": TABS, "shops": shops, "tags": tags, "carriers": carriers,
            "ids_all": [o["id"] for o in out]}


def batch(ids, action, value=None, user=""):
    n = 0
    for oid in ids:
        oid = int(oid)
        try:
            if action == "status":
                update_order(oid, user, status=value)
            elif action == "priority":
                update_order(oid, user, priority=1 if value else 0)
            elif action in ("tag_add", "tag_remove"):
                o = get_order(oid)
                tags = [t for t in (o.get("tags") or "").split(",") if t]
                v = str(value or "").strip()
                if not v:
                    continue
                tags = tags + [v] if action == "tag_add" else [t for t in tags if t != v]
                update_order(oid, user, tags=",".join(tags))
            elif action == "delete":
                delete_order(oid)
            elif action == "approve":
                set_hold(oid, False, "", user)
            elif action == "hold":
                set_hold(oid, True, str(value or "人工挂起"), user)
            elif action == "ship_method":
                update_order(oid, user, ship_method=value)
            elif action == "carrier":
                update_order(oid, user, carrier=str(value or "").strip())
            else:
                raise ValueError("不支持的操作")
            n += 1
        except ValueError:
            continue
    return n


def edit_order(oid, data, user=""):
    """修改订单（订单页「修改订单」）：基本信息 + 商品明细。
    已经开始打印的订单不能改商品（避免和生产对不上）；还没开始的会按新明细重新生成生产任务。"""
    c = db.conn()
    old = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not old:
        raise ValueError("订单不存在")
    head = {k: data[k] for k in ("buyer", "buyer_note", "seller_note", "custom_note", "kind", "receiver", "phone", "address",
                                  "postcode", "carrier", "cod", "tracking_no", "ship_by", "status", "priority", "tags",
                                  "ship_method", "payment") + MONEY_FIELDS
            if k in data}
    if head:
        update_order(oid, user, **head)
    sets = {}
    if "order_time" in data and _time(data["order_time"]):
        sets["order_time"] = _time(data["order_time"])
    for k in ("order_total", "shipping_fee", "platform_fee"):
        if k in data:
            sets[k] = _num(data[k])
    if "order_no" in data:
        no = str(data["order_no"] or "").strip()
        if not no:
            raise ValueError("订单号不能为空")
        if no != old["order_no"]:
            if old["source"] not in ("manual", None, "") and old["platform"] in ("lazada", "shopee", "tiktok"):
                raise ValueError("平台订单的订单号不能改（下次导入会对不上）")
            if c.execute("SELECT 1 FROM orders WHERE platform=? AND order_no=? AND id!=?", (old["platform"], no, oid)).fetchone():
                raise ValueError("这个订单号已经存在")
            sets["order_no"] = no
    if "shop" in data:
        sets["shop"] = str(data["shop"] or "")
    items = data.get("items")
    if items is not None:
        if not any(str(i.get("sku") or "").strip() for i in items):
            raise ValueError("至少要有一个商品")
        if _has_jobs_table(c) and c.execute(
                "SELECT COUNT(*) FROM jobs WHERE order_id=? AND (status!='todo' OR COALESCE(qty_done,0)>0 OR run_id IS NOT NULL)",
                (oid,)).fetchone()[0]:
            raise ValueError("这个订单已经开始打印了，不能再改商品。可以加备注，或者取消后重新下单")
        before = [(r["sku"], r["qty"]) for r in c.execute("SELECT sku, qty FROM order_items WHERE order_id=?", (oid,))]
        if _has_jobs_table(c):
            c.execute("DELETE FROM jobs WHERE order_id=? AND status='todo'", (oid,))
        c.execute("DELETE FROM order_items WHERE order_id=?", (oid,))
        idx = sku_index()
        for it in items:
            sku = str(it.get("sku") or "").strip()
            if not sku:
                continue
            hit = match_sku(sku, idx)
            info = _variant_info(*hit) if hit else {}
            qty = max(1, int(_num(it.get("qty")) or 1))
            unit = _num(it.get("unit_price"))
            c.execute("""INSERT INTO order_items(order_id, sku, product_id, variant_idx, name, variation, qty, unit_price,
                         item_total, color, material, grams, hours) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (oid, sku, hit[0] if hit else None, hit[1] if hit else None, it.get("name") or info.get("name", ""),
                       it.get("variation", ""), qty, unit, unit * qty if unit is not None else None,
                       info.get("color", ""), info.get("material", ""), info.get("grams"), info.get("hours")))
        after = [(str(i.get("sku") or "").strip(), max(1, int(_num(i.get("qty")) or 1))) for i in items if str(i.get("sku") or "").strip()]
        if "order_total" not in data:
            tot = c.execute("SELECT SUM(item_total) FROM order_items WHERE order_id=?", (oid,)).fetchone()[0]
            if tot is not None:
                sets["order_total"] = tot
        log(oid, user, "修改商品", "；".join(f"{s}×{q}" for s, q in before) + " → " + "；".join(f"{s}×{q}" for s, q in after),
            commit=False)
    if sets:
        sets["updated_at"] = time.time()
        c.execute(f"UPDATE orders SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), oid))
        for k in sets:
            if k in ("order_no", "order_time", "order_total", "shipping_fee", "platform_fee", "shop"):
                log(oid, user, {"order_no": "订单号", "order_time": "下单时间", "order_total": "订单金额", "shipping_fee": "运费",
                                "platform_fee": "平台费", "shop": "店铺"}[k], str(sets[k]), commit=False)
    c.commit()
    if items is not None:
        from . import chain
        chain.order_changed(user)          # v2.31：生产模块开着才生成生产任务
    return get_order(oid)


def create_manual(order, user=""):
    """手工订单：批发、大单、私下成交、预订单（报价）。"""
    if not any((it.get("sku") or "").strip() for it in order.get("items") or []):
        raise ValueError("请至少填一个商品 SKU")
    c = db.conn()
    now = time.time()
    no = (order.get("order_no") or "").strip() or f"M{dt.datetime.now().strftime('%y%m%d%H%M%S')}"
    plat = order.get("platform") or "manual"
    if c.execute("SELECT 1 FROM orders WHERE platform=? AND order_no=?", (plat, no)).fetchone():
        raise ValueError("这个订单号已经存在")
    kind = order.get("kind") or "manual"
    st = "quote" if kind == "quote" else "to_ship"
    cur = c.execute("""INSERT INTO orders(platform, shop, order_no, status, status_raw, order_time, ship_by, buyer, buyer_note,
                       custom_note, priority, order_total, shipping_fee, kind, imported_at, updated_at, source)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'manual')""",
                    (plat, order.get("shop", ""), no, st, "手工", _time(order.get("order_time")) or now,
                     _time(order.get("ship_by")), order.get("buyer", ""), order.get("buyer_note", ""),
                     order.get("custom_note", ""), int(order.get("priority") or 0), _num(order.get("order_total")),
                     _num(order.get("shipping_fee")), kind, now, now))
    oid = cur.lastrowid
    ship = {k: order.get(k) for k in ("receiver", "phone", "address", "postcode", "carrier", "cod", "tracking_no", "ship_method",
                                      "payment") if order.get(k) not in (None, "")}
    ship["buyer_key"] = buyer_key_of(plat, order.get("buyer"), order.get("phone"))
    ship["reviewed_at"], ship["reviewed_by"] = now, user or "手工"   # 手工单是自己录的，不用再审
    if "cod" in ship:
        ship["cod"] = _num(ship["cod"])
    if ship:
        c.execute(f"UPDATE orders SET {', '.join(k + '=?' for k in ship)} WHERE id=?", (*ship.values(), oid))
    idx = sku_index()
    for it in order.get("items") or []:
        sku = (it.get("sku") or "").strip()
        hit = match_sku(sku, idx)
        info = _variant_info(*hit) if hit else {}
        qty = int(_num(it.get("qty")) or 1)
        unit = _num(it.get("unit_price"))
        c.execute("""INSERT INTO order_items(order_id, sku, product_id, variant_idx, name, variation, qty, unit_price,
                     item_total, color, material, grams, hours) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (oid, sku, hit[0] if hit else None, hit[1] if hit else None, it.get("name") or info.get("name", ""),
                   it.get("variation", ""), qty, unit, unit * qty if unit is not None else None,
                   info.get("color", ""), info.get("material", ""), info.get("grams"), info.get("hours")))
    if order.get("order_total") in (None, ""):
        tot = c.execute("SELECT SUM(item_total) FROM order_items WHERE order_id=?", (oid,)).fetchone()[0]
        c.execute("UPDATE orders SET order_total=? WHERE id=?", (tot, oid))
    _auto_ship_by(c, oid)
    c.commit()
    db.audit(user, "新建手工订单", "", no)
    log(oid, user, "新建手工订单", KIND_ZH.get(kind, kind))
    return get_order(oid)


def delete_order(oid):
    c = db.conn()
    if _has_jobs_table(c):
        c.execute("DELETE FROM jobs WHERE order_id=?", (oid,))
    c.execute("DELETE FROM order_items WHERE order_id=?", (oid,))
    c.execute("DELETE FROM order_log WHERE order_id=?", (oid,))
    c.execute("DELETE FROM orders WHERE id=?", (oid,))
    c.commit()


# ---------------- v2.11 审单（挂起）----------------
REVIEW_KEYWORDS_DEFAULT = "定制,改颜色,换颜色,刻字,印字,加字,改尺寸,custom,ใส่ชื่อ,สั่งทำ,เปลี่ยนสี,สลัก,แกะชื่อ,ขอสี"


def review_flags(o, c=None):
    """按设置里的审单规则检查一个订单，返回要人工看一下的原因（空 = 没问题）。"""
    from .config import load_config
    cfg = load_config()
    c = c or db.conn()
    out = []
    amt = o.get("order_total") or 0
    over = float(cfg.get("review_amount_over") or 0)
    if over and amt >= over:
        out.append(f"金额较大（฿{amt:,.0f}）")
    words = [w.strip().lower() for w in re.split(r"[,，\n]", str(cfg.get("review_keywords") or "")) if w.strip()]
    text = f"{o.get('buyer_note') or ''} {o.get('seller_note') or ''}".lower()
    hit = [w for w in words if w in text]
    if hit:
        out.append("留言有定制要求：" + "、".join(hit[:3]))
    key = o.get("buyer_key") or ""
    prof = buyer_profile(key, c, exclude_id=o.get("id")) if key else None
    if prof and prof["level"] == "blacklist":
        out.append("黑名单买家")
    cod = is_cod(o)
    if cod and prof and prof["refused"]:
        out.append(f"货到付款，这个买家拒收过 {prof['refused']} 次")
    cod_new = float(cfg.get("review_cod_new_over") or 0)
    if cod and cod_new and amt >= cod_new and (not prof or not prof["completed"]):
        out.append(f"货到付款新客，金额 ฿{amt:,.0f}")
    hours = float(cfg.get("review_duplicate_hours") or 0)
    if hours and key and o.get("items"):
        skus = sorted((i.get("sku") or "").upper() for i in o["items"])
        for r in c.execute("SELECT id, order_no FROM orders WHERE buyer_key=? AND id!=? AND status IN ('to_ship','unpaid') "
                           "AND ABS(COALESCE(order_time,0)-?)<?", (key, o["id"], o.get("order_time") or 0, hours * 3600)):
            other = sorted((x[0] or "").upper() for x in c.execute("SELECT sku FROM order_items WHERE order_id=?", (r["id"],)))
            if other == skus:
                out.append(f"可能重复下单（和 {r['order_no']} 一样）")
                break
    return out


def auto_review(oid):
    """新订单自动审单：命中规则就「挂起」等人工审核（挂起的订单不生成生产任务），没问题就自动通过。"""
    from .config import load_config
    c = db.conn()
    o = get_order(oid)
    if not o or o["status"] != "to_ship" or o.get("reviewed_at") or o.get("hold"):
        return False
    if load_config().get("review_enabled") is False:
        return False
    flags = review_flags(o, c)
    if flags:
        c.execute("UPDATE orders SET hold=1, hold_reason=? WHERE id=?", ("；".join(flags)[:300], oid))
        log(oid, "自动审单", "挂起待审核", "；".join(flags), commit=False)
    else:
        c.execute("UPDATE orders SET reviewed_at=?, reviewed_by='自动' WHERE id=?", (time.time(), oid))
    c.commit()
    return bool(flags)


def set_hold(oid, hold, reason="", user=""):
    c = db.conn()
    o = c.execute("SELECT hold FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        raise ValueError("订单不存在")
    if hold:
        c.execute("UPDATE orders SET hold=1, hold_reason=?, updated_at=? WHERE id=?", ((reason or "人工挂起")[:300], time.time(), oid))
        log(oid, user, "挂起", reason or "", commit=False)
    else:
        c.execute("UPDATE orders SET hold=0, reviewed_at=?, reviewed_by=?, updated_at=? WHERE id=?", (time.time(), user, time.time(), oid))
        log(oid, user, "审核通过", reason or "", commit=False)
    c.commit()


SHIP_FROM = ("to_ship", "quote", "unpaid")


def on_status_change(oid, new, user="", old=None):
    """状态变化的联动：拒收 / 派送失败 → 自动登记售后（等包裹退回验货），买家档案里记一次拒收；
    待发货 → 已发货：按设置自动扣包材（v2.18）。"""
    from . import chain
    chain.order_status(oid, new, old, user)      # v2.31：库存模块开着时「已发货」自动扣包材（库存模块自己判断）
    try:                                          # v2.37：批发站的订单状态变了，马上通知批发网站
        r = db.conn().execute("SELECT platform, order_no FROM orders WHERE id=?", (oid,)).fetchone()
        if r and r["platform"] == "wholesale":
            from . import wholesale_hook
            wholesale_hook.notify(r["order_no"], new)
    except Exception as e:   # 不影响订单处理
        print("批发站回调出错：", e)
    if new == "delivery_failed":
        from . import extras
        try:
            extras.as_auto_reject(oid, user)
        except Exception as e:   # 不影响订单导入
            print("自动登记拒收售后失败：", e)


# ---------------- v2.11 买家档案 ----------------
def buyer_profile(key, c=None, exclude_id=None):
    if not key:
        return None
    c = c or db.conn()
    rows = c.execute("SELECT id, status, order_total, order_time, buyer, receiver, platform FROM orders WHERE buyer_key=?" +
                     (" AND id!=?" if exclude_id else ""), (key, exclude_id) if exclude_id else (key,)).fetchall()
    b = c.execute("SELECT * FROM buyers WHERE key=?", (key,)).fetchone()
    st = {}
    for r in rows:
        st[r["status"]] = st.get(r["status"], 0) + 1
    names = [r["buyer"] or r["receiver"] for r in rows if r["buyer"] or r["receiver"]]
    return {"key": key, "level": (b["level"] if b else "") or "", "level_zh": LEVEL_ZH.get((b["level"] if b else "") or "", ""),
            "note": (b["note"] if b else "") or "", "name": (b["name"] if b and b["name"] else (names[-1] if names else "")),
            "orders": len(rows), "completed": st.get("completed", 0) + st.get("shipped", 0),
            "refused": st.get("delivery_failed", 0), "returned": st.get("returned", 0), "cancelled": st.get("cancelled", 0),
            "spent": round(sum((r["order_total"] or 0) for r in rows if r["status"] in ("completed", "shipped", "to_ship")), 2),
            "first": min((r["order_time"] or 0 for r in rows), default=None),
            "last": max((r["order_time"] or 0 for r in rows), default=None),
            "platforms": sorted({r["platform"] for r in rows if r["platform"]})}


def buyer_risk(p, cod=False):
    """订单列表上显示的小标签。"""
    if not p:
        return []
    out = []
    if p["level"] in ("vip", "wholesale", "blacklist", "watch"):
        out.append(p["level"])
    if p["refused"]:
        out.append(f"refused:{p['refused']}")
    if p["orders"] <= 1:
        out.append("new")
    elif p["orders"] > 1:
        out.append(f"repeat:{p['orders']}")
    return out


def buyer_set(key, level=None, note=None, name=None, user=""):
    if not key:
        raise ValueError("这个订单没有买家信息")
    if level is not None and level not in LEVEL_ZH:
        raise ValueError("买家分类不对")
    c = db.conn()
    old = c.execute("SELECT * FROM buyers WHERE key=?", (key,)).fetchone()
    cur = dict(old) if old else {"key": key, "name": "", "level": "", "note": ""}
    if level is not None:
        cur["level"] = level
    if note is not None:
        cur["note"] = str(note)[:500]
    if name is not None:
        cur["name"] = str(name)[:80]
    c.execute("INSERT INTO buyers(key, name, level, note, updated_at, username) VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
              "name=excluded.name, level=excluded.level, note=excluded.note, updated_at=excluded.updated_at, username=excluded.username",
              (key, cur["name"], cur["level"], cur["note"], time.time(), user))
    c.commit()
    db.audit(user, "买家档案", key, f"{LEVEL_ZH.get(cur['level'], cur['level'])} {cur['note']}".strip())
    return buyer_profile(key)


def buyers_list(q="", level="", risky=False, limit=300):
    """买家档案列表：有分类 / 拒收过 / 下过 2 单以上的买家。"""
    c = db.conn()
    rows = c.execute("""SELECT buyer_key AS k, COUNT(*) AS n, SUM(status='delivery_failed') AS refused, SUM(status='returned') AS returned,
                        SUM(CASE WHEN status IN ('completed','shipped','to_ship') THEN COALESCE(order_total,0) ELSE 0 END) AS spent,
                        MAX(order_time) AS last, MAX(COALESCE(NULLIF(buyer,''), receiver)) AS name, MAX(platform) AS platform
                        FROM orders WHERE COALESCE(buyer_key,'')!='' GROUP BY buyer_key""").fetchall()
    marks = {r["key"]: dict(r) for r in c.execute("SELECT * FROM buyers")}
    out = []
    for r in rows:
        m = marks.pop(r["k"], None) or {}
        d = {"key": r["k"], "name": m.get("name") or r["name"] or "", "level": m.get("level") or "", "note": m.get("note") or "",
             "orders": r["n"], "refused": r["refused"] or 0, "returned": r["returned"] or 0, "spent": round(r["spent"] or 0, 2),
             "last": r["last"], "platform": r["platform"]}
        out.append(d)
    for k, m in marks.items():   # 标记过但订单删了
        out.append({"key": k, "name": m.get("name") or "", "level": m.get("level") or "", "note": m.get("note") or "", "orders": 0,
                    "refused": 0, "returned": 0, "spent": 0, "last": None, "platform": ""})
    if level:
        out = [d for d in out if d["level"] == level]
    elif risky:
        out = [d for d in out if d["refused"] or d["level"] in ("blacklist", "watch")]
    else:
        out = [d for d in out if d["level"] or d["refused"] or d["orders"] >= 2]
    if q:
        ql = q.strip().lower()
        out = [d for d in out if ql in (d["name"] or "").lower() or ql in d["key"]]
    out.sort(key=lambda d: (-(d["level"] == "blacklist"), -d["refused"], -d["orders"], -(d["last"] or 0)))
    for d in out:
        d["level_zh"] = LEVEL_ZH.get(d["level"], d["level"])
        d["key_show"] = mask_key(d["key"])
    return out[:limit]


def mask_key(key):
    if key.startswith("p:"):
        return "电话 ***" + key[-4:]
    return key.split(":", 2)[-1] if key.startswith("b:") else key


# ---------------- v2.11 运单号批量导入 ----------------
def import_tracking(text, mark_shipped=False, user=""):
    """每行：订单号, 运单号[, 物流公司]（逗号 / Tab / 空格分隔）。"""
    c = db.conn()
    done, missing, bad = [], [], []
    for n, line in enumerate(str(text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in re.split(r"[,\t，;；]|\s{1,}", line, maxsplit=2) if x.strip()]
        if len(parts) < 2:
            bad.append(n); continue
        no, track = parts[0], parts[1]
        carrier = parts[2] if len(parts) > 2 else None
        r = c.execute("SELECT id FROM orders WHERE order_no=? ORDER BY id DESC LIMIT 1", (no,)).fetchone()
        if not r:
            missing.append(no); continue
        kw = {"tracking_no": track}
        if carrier:
            kw["carrier"] = carrier
        if mark_shipped:
            cur = c.execute("SELECT status FROM orders WHERE id=?", (r["id"],)).fetchone()["status"]
            if cur == "to_ship":
                kw["status"] = "shipped"
        update_order(r["id"], user, **kw)
        done.append(no)
    if done:
        db.audit(user, "批量导入运单号", "", f"{len(done)} 个订单")
    return {"updated": len(done), "not_found": missing, "bad_lines": bad}


# ---------------- v2.11 发货交接单 ----------------
def handover_open(carrier="", method="", user=""):
    """当前还没交接的单（同一物流 + 方式只开一张）。"""
    c = db.conn()
    r = c.execute("SELECT id FROM handovers WHERE closed_at IS NULL AND COALESCE(carrier,'')=? AND COALESCE(method,'')=? "
                  "ORDER BY id DESC LIMIT 1", (carrier or "", method or "")).fetchone()
    if r:
        return r["id"]
    hid = c.execute("INSERT INTO handovers(carrier, method, created_at, username) VALUES(?,?,?,?)",
                    (carrier or "", method or "", time.time(), user)).lastrowid
    c.commit()
    return hid


def handover_get(hid):
    c = db.conn()
    h = c.execute("SELECT * FROM handovers WHERE id=?", (hid,)).fetchone()
    if not h:
        return None
    d = dict(h)
    d["method_zh"] = SHIP_METHOD_ZH.get(d["method"] or "", d["method"] or "")
    d["orders"] = [dict(r) for r in c.execute(
        "SELECT id, order_no, platform, shop, tracking_no, carrier, receiver, buyer, status, cod, payment, label_printed_at "
        "FROM orders WHERE handover_id=? ORDER BY updated_at", (hid,))]
    for o in d["orders"]:
        o["status_zh"] = STATUS_ZH.get(o["status"], o["status"])
        o["n_items"] = c.execute("SELECT COALESCE(SUM(qty),0) FROM order_items WHERE order_id=?", (o["id"],)).fetchone()[0]
    d["count"] = len(d["orders"])
    d["cod_total"] = round(sum((o["cod"] or 0) for o in d["orders"]), 2)
    return d


def handover_list(limit=50):
    c = db.conn()
    out = []
    for h in c.execute("SELECT * FROM handovers ORDER BY closed_at IS NOT NULL, id DESC LIMIT ?", (int(limit),)):
        d = dict(h)
        d["method_zh"] = SHIP_METHOD_ZH.get(d["method"] or "", d["method"] or "")
        d["count"] = c.execute("SELECT COUNT(*) FROM orders WHERE handover_id=?", (h["id"],)).fetchone()[0]
        out.append(d)
    return out


def handover_scan(hid, code, user=""):
    """扫面单上的运单号或订单号，加进交接单。返回 {ok, order, warn}。"""
    c = db.conn()
    h = c.execute("SELECT * FROM handovers WHERE id=?", (hid,)).fetchone()
    if not h:
        raise ValueError("交接单不存在")
    if h["closed_at"]:
        raise ValueError("这张交接单已经完成了，请新开一张")
    code = str(code or "").strip()
    if not code:
        raise ValueError("请扫描运单号或订单号")
    from modules.orders import scanning          # v2.32：扫什么码按设置（订单号 / 快递单号）
    r = scanning.find_order(code)
    if not r:
        raise ValueError(scanning.not_found_msg(code))
    if r["status"] in ("cancelled", "returned", "delivery_failed"):
        raise ValueError(f"订单 {r['order_no']} 是「{STATUS_ZH.get(r['status'])}」状态，不能发货！")
    if r["hold"]:
        raise ValueError(f"订单 {r['order_no']} 还在「待审核」挂起中，先审核通过再发")
    if r["handover_id"] == hid:
        raise ValueError(f"订单 {r['order_no']} 已经扫过了")
    warn = []
    if r["handover_id"]:
        o2 = c.execute("SELECT closed_at FROM handovers WHERE id=?", (r["handover_id"],)).fetchone()
        if o2 and o2["closed_at"]:
            raise ValueError(f"订单 {r['order_no']} 已经在第 {r['handover_id']} 号交接单里交出去了")
        warn.append(f"从第 {r['handover_id']} 号交接单移过来")
    if h["carrier"] and r["carrier"] and h["carrier"].lower() not in r["carrier"].lower() and r["carrier"].lower() not in h["carrier"].lower():
        warn.append(f"物流不一样：订单是 {r['carrier']}")
    if not r["tracking_no"]:
        warn.append("订单还没有运单号")
    if _has_jobs_table(c):
        left = c.execute("SELECT COUNT(*) FROM jobs WHERE order_id=? AND status NOT IN ('packed','done')", (r["id"],)).fetchone()[0]
        if left:
            warn.append(f"还有 {left} 个生产任务没打包")
    c.execute("UPDATE orders SET handover_id=?, updated_at=? WHERE id=?", (hid, time.time(), r["id"]))
    log(r["id"], user, "加入交接单", f"#{hid} {h['carrier'] or ''}", commit=False)
    c.commit()
    return {"order": {"id": r["id"], "order_no": r["order_no"], "tracking_no": r["tracking_no"]}, "warn": warn}


def handover_remove(hid, oid, user=""):
    c = db.conn()
    h = c.execute("SELECT closed_at FROM handovers WHERE id=?", (hid,)).fetchone()
    if h and h["closed_at"]:
        raise ValueError("已经交接完成的单不能再改")
    c.execute("UPDATE orders SET handover_id=NULL WHERE id=? AND handover_id=?", (oid, hid))
    log(oid, user, "移出交接单", f"#{hid}", commit=False)
    c.commit()


def handover_close(hid, user=""):
    """交接完成：单里的订单都标记「已发货」，生产任务标记已发货。"""
    d = handover_get(hid)
    if not d:
        raise ValueError("交接单不存在")
    if d["closed_at"]:
        raise ValueError("这张交接单已经完成了")
    if not d["orders"]:
        raise ValueError("交接单里还没有订单")
    c = db.conn()
    n = 0
    for o in d["orders"]:
        if o["status"] in ("to_ship", "unpaid", "quote", "other"):
            update_order(o["id"], user, status="shipped")
            n += 1
        if _has_jobs_table(c):
            c.execute("UPDATE jobs SET status='done', done_at=?, updated_at=?, updated_by=? WHERE order_id=? AND status IN ('packed','post')",
                      (time.time(), time.time(), user, o["id"]))
        log(o["id"], user, "交接给物流", f"#{hid} {d['carrier'] or ''}", commit=False)
    c.execute("UPDATE handovers SET closed_at=?, closed_by=? WHERE id=?", (time.time(), user, hid))
    c.commit()
    db.audit(user, "发货交接", f"#{hid}", f"{d['carrier']} {len(d['orders'])} 单")
    return {"shipped": n, "count": len(d["orders"])}


def handover_delete(hid):
    c = db.conn()
    h = c.execute("SELECT closed_at FROM handovers WHERE id=?", (hid,)).fetchone()
    if not h:
        return
    if h["closed_at"]:
        raise ValueError("已经交接完成的单不能删除")
    c.execute("UPDATE orders SET handover_id=NULL WHERE handover_id=?", (hid,))
    c.execute("DELETE FROM handovers WHERE id=?", (hid,))
    c.commit()
