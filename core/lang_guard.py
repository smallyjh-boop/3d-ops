"""导出 / 对接平台的内容只能是泰文和英文（v2.19.1）：把要导出的每一行逐个字段查一遍，有中文就列出来（上架检查报红，不能导出）。
中文只用在系统内部（产品名、颜色和规格的中文键、备注），不会出现在平台上。"""
import copy
import re

CJK = re.compile(r"[㐀-鿿豈-﫿]")
SKIP = ("__", "mainImage", "marketImages", "sku.images", "customSaleProp.First_Custom_Opt_Img", "ps_item_image", "ps_item_cover_image",
        "sku.SellerSku", "ps_sku")
LABELS = {
    "title": "泰文标题", "title.en_TH": "英文标题", "description": "泰文详情", "enDescription": "英文详情", "packageContent": "包装内容",
    "customSaleProp.Custom_Variation_Name_1": "变体1名称", "customSaleProp.Custom_Variation_Name_2": "变体2名称",
    "customSaleProp.Custom_Opt_Name_1": "颜色 / 选项1", "customSaleProp.Custom_Opt_Name_2": "规格 / 选项2",
    "ps_product_name": "Shopee 标题", "ps_product_description": "Shopee 详情", "et_title_variation_1": "Shopee 变体1名称",
    "et_title_variation_2": "Shopee 变体2名称", "et_title_option_for_variation_1": "Shopee 选项1", "et_title_option_for_variation_2": "Shopee 选项2",
}


def _scan(rows, attr_labels=None):
    out = {}
    for row in rows:
        vals = row[2] if isinstance(row, tuple) else row
        for k, v in vals.items():
            if not isinstance(v, str) or k.startswith(SKIP) or not CJK.search(v):
                continue
            lab = LABELS.get(k) or (attr_labels or {}).get(k) or k
            out.setdefault(lab, v.strip()[:30])
    return [f"导出到平台的「{lab}」里还有中文（{sample}…），平台上只能用泰文 / 英文" for lab, sample in out.items()]


def lazada_problems(p, prices, cfg, cat):
    from . import lazada_template
    if cat is None:
        return []
    q = copy.deepcopy(p)
    try:
        rows = lazada_template.build_rows([q], {q["id"]: prices}, cfg, cat)
    except Exception:  # noqa: BLE001  别的检查会报具体问题
        return []
    labels = {f["key"]: "属性「" + (f.get("label") or f["key"]) + "」" for f in cat.get("fields") or []}
    for k, a in (p.get("attributes") or {}).items():
        if a.get("label_zh"):
            labels[k] = "属性「" + a["label_zh"] + "」"
    return _scan(rows, labels)


def shopee_problems(p, prices, cfg):
    from . import shopee
    q = copy.deepcopy(p)
    try:
        rows = shopee.build_rows([q], {q["id"]: prices}, cfg)
    except Exception:  # noqa: BLE001
        return []
    return [x.replace("导出到平台", "导出到 Shopee") for x in _scan(rows)]
