"""3D 模型（基础模块）：产品的 3D 模型上传 / 预览 / 历史、模型库（多个文件、拼盘）、规格对应的模型、几何分析、
AI 打印建议、估算克数和时长（切片估算）。编辑产品页里的 3D 部分（界面代码 v2.32 从 app.js 拆出来）。

v2.52 分三层：模型文件库（原始文件，modellib）→ 展示模型（assembly.py：组装姿势、颜色效果、商品图）
             → 打印方案（printplan.py：每个规格几盘、手动摆盘、AMS 多色槽、配色方案；生产、成本、扣耗材都按它）。
v2.53：展示和打印完全分开（展示有自己的零件选择，合并成一套只影响打印）；每个规格各有展示和方案；自动组合（mating.py）。"""
from . import printplan

MODULE = {
    "id": "model",
    "name_zh": "3D 模型",
    "name_th": "โมเดล 3D",
    "version": "1.3",
    "desc_zh": "产品 3D 模型、模型库、规格模型、展示模型（组装）、打印方案（摆盘、多色 AMS）、几何分析、AI 打印建议、估算克数和时长。",
    "desc_th": "โมเดล 3D ของสินค้า คลังโมเดล โมเดลตามตัวเลือก โมเดลแสดงผล (ประกอบ) แผนการพิมพ์ (จัดวางถาด หลายสี AMS) "
               "วิเคราะห์รูปทรง คำแนะนำการพิมพ์จาก AI และประมาณกรัม/เวลา",
    "core": True,
    "public": printplan,
    "depends": ["goods"],
    "order": 3,
    # 打印方案、展示模型：生产员工也要用（排盘、看颜色）；合并成模型 = 换 3D 模型，要「换模型」权限
    "production_allow": [("GET", r"^/api/products/[^/]+/(print-plan|display)(/[\w.-]+)*$"),
                         ("GET", r"^/api/products/[^/]+/model-status$"),
                         ("GET", r"^/api/products/[^/]+/physical$"), ("POST", r"^/api/products/[^/]+/physical(/slice)?$"),
                         ("POST", r"^/api/products/[^/]+/print-plan(/(footprint|check|kit|slice|slice-all|fill|merge|copy|from-display|op|orients))?$"),
                         ("POST", r"^/api/products/[^/]+/display(/(ai|auto-select|auto-assemble|settle|explode|copy))?$"),
                         ("POST", r"^/api/products/[^/]+/spec-scale$"),
                         # v2.56（T36）：在切片软件里编辑一盘（权限和保存打印方案一样）
                         ("POST", r"^/api/products/[^/]+/print-plan/edit/(start|finish|abandon|upload|confirm)$")],
    "public_paths": ["/api/slicer-edit/"],      # 带会话密钥：桌面客户端下载编辑文件 / 保存后自动回传
    "perm_rules": [("POST", r"^/api/products/[^/]+/print-plan/merge$", "models.change")],
    "settings_module": "cost",
    "settings": [("多色打印（AMS）估算：没有切片结果时用", [
        ("mc_purge_g", "每次换色冲刷掉的料（克，估算用；拓竹默认冲刷量大约 1–2 克）"),
        ("mc_change_s", "每次换色多花的时间（秒，AMS 退料 + 进料 + 冲刷）")])],
    "config_defaults": {"mc_purge_g": 1.5, "mc_change_s": 50},
    "ui": {"eager_js": ["model.js", "plan.js", "m3.js", "slicedit.js"], "page_js": [], "boot_js": []},
}
