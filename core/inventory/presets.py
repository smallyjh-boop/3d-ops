"""常用物品清单（v2.19.1）：第一次启动时自动建好（数量 0，录入现有库存或开采购单就行），以后也可以在库存页点「补全常用物品」。
已经有的（耗材按 材料 + 颜色，其他按中文名）不会重复建。

耗材颜色按 2026-10 的颜色分析：白、黑、粉卖得最多（补货线 1.5 卷、每次补 3 卷），其余每色 1 卷起（补货线半卷、每次补 1 卷）。
"""
import os

from ..config import load_config, save_config
from . import ledger

# (颜色, 补货线 g, 每次补 g)
PLA_COLORS = [
    ("白色", 1500, 3000), ("黑色", 1500, 3000), ("粉色", 1500, 2000), ("灰色", 500, 2000), ("米色", 500, 2000),
    ("天蓝色", 500, 2000), ("紫色", 500, 1000), ("绿色", 500, 1000), ("黄色", 500, 1000), ("红色", 500, 1000),
    ("棕色", 500, 1000), ("橙色", 500, 1000),
]
OTHER_FILAMENT = [("PETG", "黑色", 500, 1000), ("PETG", "白色", 500, 1000), ("TPU", "黑色", 300, 1000)]

# (分类, 中文名, 泰文名, 单位, 规格, 补货线, 每次补)
ITEMS = [
    # 生产：备件 / 耗品
    ("part", "喷嘴 0.4mm（硬化钢）", "หัวฉีด 0.4mm (เหล็กชุบแข็ง)", "个", "Bambu P1S / K1 通用请按机型买", 2, 4),
    ("part", "喷嘴 0.4mm（K1 / K1 Max）", "หัวฉีด 0.4mm (K1 / K1 Max)", "个", "Creality K 系列", 2, 4),
    ("part", "PEI 热床板", "แผ่นฐานพิมพ์ PEI", "张", "按打印机尺寸", 1, 1),
    ("part", "PTFE 管（1 米）", "ท่อ PTFE (1 เมตร)", "根", "", 1, 2),
    ("part", "打印机润滑脂", "จาระบีเครื่องพิมพ์", "支", "", 1, 1),
    ("part", "干燥剂（耗材盒用）", "สารดูดความชื้น (กล่องฟิลาเมนต์)", "包", "可再生硅胶", 5, 20),
    ("part", "固体胶 / 热床胶", "กาวติดฐานพิมพ์", "支", "PETG / ABS 防翘边", 1, 3),
    ("part", "异丙醇（清洁热床）", "แอลกอฮอล์ IPA (ทำความสะอาดฐาน)", "瓶", "500ml", 1, 2),
    ("part", "光固化树脂（标准灰）", "เรซิ่น (สีเทามาตรฐาน)", "瓶", "1kg", 1, 2),
    ("part", "离型膜 FEP（光固化）", "ฟิล์ม FEP (เรซิ่น)", "张", "Photon Mono M5s", 1, 2),
    ("part", "一次性手套", "ถุงมือใช้แล้วทิ้ง", "盒", "", 1, 2),
    ("tool", "铲刀", "ที่แซะชิ้นงาน", "把", "", 1, 1),
    ("tool", "斜口钳", "คีมตัด", "把", "去支撑", 1, 1),
    ("tool", "美工刀 / 修边刀", "มีดคัตเตอร์ / มีดแต่งขอบ", "把", "", 1, 1),
    ("tool", "砂纸（多目数）", "กระดาษทราย (หลายเบอร์)", "张", "400 / 800 / 1500", 10, 30),
    # 打包
    ("pack", "纸箱 S", "กล่องกระดาษ S", "个", "约 15×15×10 cm", 20, 100),
    ("pack", "纸箱 M", "กล่องกระดาษ M", "个", "约 20×20×15 cm", 20, 100),
    ("pack", "纸箱 L", "กล่องกระดาษ L", "个", "约 30×25×20 cm", 10, 50),
    ("pack", "快递袋", "ถุงไปรษณีย์", "个", "25×35 cm", 30, 200),
    ("pack", "气泡膜", "บับเบิ้ล", "卷", "", 1, 2),
    ("pack", "气泡袋", "ซองบับเบิ้ล", "个", "", 30, 200),
    ("pack", "封箱胶带", "เทปปิดกล่อง", "卷", "", 3, 12),
    ("pack", "热敏面单纸 100×150", "กระดาษสติกเกอร์ความร้อน 100×150", "卷", "", 2, 5),
    ("pack", "自封袋", "ถุงซิปล็อค", "个", "装小件 / 防潮", 50, 300),
    ("pack", "填充纸 / 碎纸", "กระดาษกันกระแทก", "包", "", 1, 3),
    ("pack", "感谢卡", "การ์ดขอบคุณ", "张", "", 50, 300),
]


def seed(user="系统"):
    """建好还没有的常用物品，返回新建的个数。"""
    from .. import codes, db
    cfg = load_config()
    c = db.conn()
    n = 0
    fil = [("PLA", col, rp, rq) for col, rp, rq in PLA_COLORS] + list(OTHER_FILAMENT)
    for mat, col, rp, rq in fil:
        if c.execute("SELECT 1 FROM inv_items WHERE category='filament' AND material=? AND color=?", (mat, col)).fetchone():
            continue
        hit = codes.find_color(cfg, col)
        th = hit[2] if hit and hit[2] else col
        try:
            ledger.save_item({"name_zh": f"{mat} {col}", "name_th": f"{mat} {th}", "category": "filament", "unit": "g",
                              "material": mat, "color": col, "reorder_point": rp, "reorder_qty": rq, "spec": "1 kg / 卷"}, user)
            n += 1
        except ValueError:
            pass
    for cat, zh, th, unit, spec, rp, rq in ITEMS:
        if c.execute("SELECT 1 FROM inv_items WHERE name_zh=?", (zh,)).fetchone():
            continue
        try:
            ledger.save_item({"name_zh": zh, "name_th": th, "category": cat, "unit": unit, "spec": spec,
                              "reorder_point": rp, "reorder_qty": rq}, user)
            n += 1
        except ValueError:
            pass
    return n


def seed_once():
    """第一次启动 v2.19.1 时建一次（测试环境 LH_NO_PRESETS=1 时不建）。"""
    if os.environ.get("LH_NO_PRESETS"):
        return 0
    cfg = load_config()
    if cfg.get("inv_presets_done"):
        return 0
    n = seed()
    save_config({"inv_presets_done": True})
    return n
