"""拍照识别（v1.0）：
· 拍照找产品：很多产品没有条码——员工用手机拍一下实物，系统找出是哪个产品 / SKU（本地比特征取前 8 个，再让 AI 看图挑），
  点「就是它」就当成扫了这个 SKU（验货、查库存、放货位、查订单都一样）；确认过的照片自动变成参考图，越用越准。
· 拍照读文字：货位牌、面单、标签上的字（条码坏了也行）→ 货位编号 / 订单号 / 快递单号 / SKU（容忍 O/0、I/1、少横杠这类错）。
  安卓 App 的摄像头小窗也用 ML Kit 认文字，像扫码一样送进来（带「文字」小标）。
· 识别测试页：老板上传一批实物照片（文件名可以带正确 SKU）看认得准不准。
参考图：产品图 + 服务器从 3D 模型画的多角度图（不用显卡）+ 员工确认过的照片；产品改了自动重算。"""

from . import public


def _start():
    from . import refs
    refs.start_build()          # 开机补建 / 更新参考图（没变的产品跳过）


MODULE = {
    "id": "recog",
    "name_zh": "拍照识别（产品 / 文字）",
    "name_th": "ถ่ายรูปจดจำ (สินค้า / ตัวอักษร)",
    "version": "1.1",
    "desc_zh": "拍照找产品（没有条码的产品拍一下就知道是哪个 SKU）；拍照读货位牌 / 面单上的字；安卓 App 摄像头也认文字。",
    "desc_th": "ถ่ายรูปหาสินค้า (สินค้าไม่มีบาร์โค้ด ถ่ายรูปก็รู้ว่าเป็น SKU ไหน) ถ่ายรูปอ่านป้ายตำแหน่ง / ใบปะหน้า กล้องในแอป Android ก็อ่านตัวอักษรได้",
    "depends": [],
    "order": 86,
    "public": public,             # 别的模块用：match_text（文字容错认码）、code_patterns（手机 App 的正则）
    "menus": [{"tab": "recog_test", "mod": "sys", "zh": "识别测试", "th": "ทดสอบการจดจำ", "roles": "owner,listing"}],
    "settings_module": "addons",
    "settings_cards": ["addons"],
    "settings": [("拍照识别（产品 / 文字）", [
        ("recog_on", "打开拍照识别（手机页、App、打包核对的 📷 按钮）", "bool"),
        ("recog_ai", "让 AI 看图帮忙挑（每拍一次算一次 AI 调用）：auto = AI 能看图就用；on = 一直用；off = 只用本地比对（不花钱）",
         ["auto", "on", "off"]),
        ("recog_ai_daily", "AI 看图每天最多几次（0 = 不限）"),
        ("recog_threshold", "把握够多少就直接用第一个（0.5~0.95；低于这个让员工从前 3 个里点）"),
        ("recog_learn", "员工确认过的照片存成参考图（越用越准）", "bool"),
        ("recog_ocr_ai", "拍照读文字：本地没有 OCR 时用 AI 看图读字", "bool")])],
    "config_defaults": {"recog_on": True, "recog_ai": "auto", "recog_ai_daily": 300, "recog_threshold": 0.75, "recog_learn": True,
                        "recog_ocr_ai": True},
    "public_paths": ["/m/recog/m_recog.js", "/m/recog/recog_ui.js"],     # 手机页登录前就加载的脚本（没有数据）
    "production_allow": [("GET", r"^/api/recog/(search|text|disp/|query/|status$)"),
                         ("POST", r"^/api/recog/(identify|confirm|unconfirm|ocr)$")],
    "owner_only": [("POST", r"^/api/recog/model/")],
    "startup": _start,
    "ui": {"html": "page.html", "page_js": ["page.js"], "boot_js": ["recog_ui.js", "desk.js"], "css": []},
}
