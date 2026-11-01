"""3D 模型（基础模块）：产品的 3D 模型上传 / 预览 / 历史、模型库（多个文件、拼盘）、规格对应的模型、几何分析、
AI 打印建议、估算克数和时长（切片估算）。编辑产品页里的 3D 部分（界面代码 v2.32 从 app.js 拆出来）。

v2.52 分三层：模型文件库（原始文件，modellib）→ 展示模型（assembly.py：组装姿势、颜色效果、商品图）
             → 打印方案（printplan.py：每个规格几盘、手动摆盘、AMS 多色槽、配色方案；生产、成本、扣耗材都按它）。"""
from . import printplan

MODULE = {
    "id": "model",
    "name_zh": "3D 模型",
    "name_th": "โมเดล 3D",
    "version": "1.2",
    "desc_zh": "产品 3D 模型、模型库、规格模型、展示模型（组装）、打印方案（摆盘、多色 AMS）、几何分析、AI 打印建议、估算克数和时长。",
    "desc_th": "โมเดล 3D ของสินค้า คลังโมเดล โมเดลตามตัวเลือก โมเดลแสดงผล (ประกอบ) แผนการพิมพ์ (จัดวางถาด หลายสี AMS) "
               "วิเคราะห์รูปทรง คำแนะนำการพิมพ์จาก AI และประมาณกรัม/เวลา",
    "core": True,
    "public": printplan,
    "depends": ["goods"],
    "order": 3,
    # 打印方案、展示模型：生产员工也要用（排盘、看颜色）；合并成模型 = 换 3D 模型，要「换模型」权限
    "production_allow": [("GET", r"^/api/products/[^/]+/(print-plan|display)(/[\w.-]+)*$"),
                         ("POST", r"^/api/products/[^/]+/print-plan(/(footprint|check|kit|slice|fill|merge))?$"),
                         ("POST", r"^/api/products/[^/]+/display(/ai)?$")],
    "perm_rules": [("POST", r"^/api/products/[^/]+/print-plan/merge$", "models.change")],
    "settings_module": "cost",
    "settings": [("多色打印（AMS）估算：没有切片结果时用", [
        ("mc_purge_g", "每次换色冲刷掉的料（克，估算用；拓竹默认冲刷量大约 1–2 克）"),
        ("mc_change_s", "每次换色多花的时间（秒，AMS 退料 + 进料 + 冲刷）")])],
    "config_defaults": {"mc_purge_g": 1.5, "mc_change_s": 50},
    "ui": {"eager_js": ["model.js", "plan.js"], "page_js": [], "boot_js": []},
}
