"""上架检查的额外规则（v2.50，从「3D选品工具」的文案检查和选品排除规则搬进 ERP 的上架检查，所有产品都用）：
  · 品牌 / 动漫 / 游戏角色词（在 Lazada、Shopee 卖印出来的实物有侵权风险）
  · 标题 / 规格名里的颜色词（颜色由 ERP 的颜色表管理）、营销词（平台不允许）、需要证明的功能说法、店铺 / 发货说法
  · 泰国市场的敏感品类：儿童玩具（要 มอก. 认证）、宗教造型、类似武器、接触食物、成人用品
  · 许可待核验：从选品来的草稿（p["license_check"].status == "pending"）—— 这一条是错误，挡导出 / 推送
对外：problems(p) → (errors, warnings)，lazada_template.check_product 调用；word lists 也给选品模块（modules/curate/rules.py）打分用。
"""
import re

IP_TERMS = [
    "hello kitty", "sanrio", "kuromi", "my melody", "cinnamoroll", "pompompurin", "pokemon", "pokémon", "pikachu", "nintendo", "mario", "zelda",
    "kirby", "disney", "mickey", "minnie", "stitch", "frozen", "marvel", "avengers", "spiderman", "spider-man", "iron man", "batman", "superman",
    "dc comics", "star wars", "mandalorian", "baby yoda", "grogu", "darth vader", "harry potter", "hogwarts", "lego", "minecraft", "fortnite", "roblox",
    "among us", "sonic", "barbie", "doraemon", "one piece", "naruto", "dragon ball", "goku", "totoro", "ghibli", "labubu", "pop mart", "sesame street",
    "snoopy", "peanuts", "garfield", "spongebob", "paw patrol", "peppa pig", "bluey", "transformers", "warhammer", "gundam", "evangelion",
    "jujutsu kaisen", "demon slayer", "kimetsu", "chainsaw man", "attack on titan", "genshin", "hatsune miku",
    "apple watch", "airtag", "macbook", "airpods", "ikea", "coca cola", "starbucks", "nike", "adidas", "tesla", "ferrari", "porsche", "bmw",
    "mercedes", "lamborghini",
    "凯蒂猫", "三丽鸥", "库洛米", "美乐蒂", "宝可梦", "皮卡丘", "任天堂", "马里奥", "迪士尼", "米老鼠", "史迪奇", "漫威", "蜘蛛侠", "钢铁侠", "蝙蝠侠",
    "星球大战", "哈利波特", "乐高", "我的世界", "芭比", "哆啦A梦", "海贼王", "火影", "龙珠", "龙猫", "宫崎骏", "拉布布", "泡泡玛特", "史努比", "高达",
    "คิตตี้", "โปเกมอน", "ปิกาจู", "โดราเอมอน", "มาริโอ้", "ดิสนีย์", "มาร์เวล", "ลาบูบู้",
]
COLOR_WORDS = ["白色", "黑色", "红色", "粉色", "蓝色", "绿色", "黄色", "紫色", "灰色", "金色", "银色", "橙色", "棕色", "彩虹", "渐变", "夜光", "多色", "彩色",
               "สีขาว", "สีดำ", "สีแดง", "สีชมพู", "สีฟ้า", "สีน้ำเงิน", "สีเขียว", "สีเหลือง", "สีม่วง", "สีเทา", "สีทอง", "สีเงิน", "สีส้ม", "สีน้ำตาล",
               "สีรุ้ง", "ไล่สี", "เรืองแสง", "หลากสี",
               "white", "black", "red", "pink", "blue", "green", "yellow", "purple", "grey", "gray", "gold", "silver", "orange", "brown", "rainbow",
               "gradient", "multicolor"]
MARKETING_WORDS = ["热卖", "爆款", "限量", "特价", "秒杀", "包邮", "正品", "最便宜", "ขายดี", "ลดราคา", "ราคาถูก", "ส่งฟรี", "ของแท้",
                   "best seller", "hot sale", "free shipping"]
CLAIM_WORDS = ["食品级", "可接触食物", "无毒", "儿童安全", "医用", "防火",
               "ฟู้ดเกรด", "สัมผัสอาหาร", "ไร้สารพิษ", "ปลอดภัยสำหรับเด็ก",
               "food safe", "food grade", "non-toxic", "child safe", "baby safe"]
SENSITIVE = [   # (原因, 关键词)
    ("儿童玩具（泰国要求 TISI 认证）", r"for kids|for children|\bbaby\b|toddler|infant|teether|rattle|ของเล่นเด็ก|儿童玩具|婴儿|ทารก"),
    ("宗教造型（佛像等，敏感）", r"buddha|\bmonk\b|ganesh|พระพุทธ|พระเครื่อง|佛像|菩萨|\bjesus\b|crucifix"),
    ("类似武器", r"\bgun\b(?! ?(?:holder|stand|mount|rack))|pistol|rifle|\bknife\b(?! ?(?:holder|block|rack|sharpener|stand))|dagger|\bsword\b|katana|crossbow|grenade|\bammo\b|weapon|手枪|步枪|武器|ปืน"),
    ("接触食物（打印件不卫生）", r"cookie cutter|food safe|food grade|\bmug\b|cutlery|\bspoon\b(?! ?rest)|\bfork\b|drinking straw|餐具|饼干模|ฟู้ดเกรด"),
    ("成人用品", r"\bsex\b|adult toy|erotic|nsfw|情趣"),
]


def words_in(text, words):
    """text 里出现的词（英文按整词，中泰文按包含）。"""
    t = (text or "").lower()
    out = []
    for w in words:
        if re.fullmatch(r"[a-z \-é]+", w):
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", t):
                out.append(w)
        elif w in t:
            out.append(w)
    return out


def sensitive(text):
    for why, pat in SENSITIVE:
        if re.search(pat, text or "", re.I):
            return why
    return ""


def license_pending(p):
    lc = p.get("license_check") or {}
    return lc.get("status") == "pending"


def problems(p):
    """(errors, warnings)。"""
    errors, warnings = [], []
    if license_pending(p):
        lc = p["license_check"]
        errors.append("许可待核验：这个产品是从模型网站采用的，要有人打开原站确认许可可以商用（编辑页上面「核验许可」）才能导出 / 推送"
                      + (f"（原站许可：{lc.get('name')}）" if lc.get("name") else ""))
    c = p.get("copy") or {}
    titles = " ".join(str(c.get(k) or "") for k in ("title_th", "title_shopee_th", "title_en"))
    names = titles + " " + str(p.get("name_zh") or "")
    allt = names + " " + " ".join(str(c.get(k) or "") for k in ("description_th", "description_en", "package_content_th")) + " " + \
        " ".join(str(x) for x in c.get("highlights_th") or [])
    ir = p.get("ip_risk") or {}
    if ir.get("status") != "ok":
        hit = words_in(names + " " + str((p.get("source") or {}).get("title_original") or ""), IP_TERMS)
        if hit and not (ir.get("status") == "pending" and ir.get("items")):
            warnings.append("可能侵权：标题里有品牌 / 动漫角色词（" + "、".join(hit[:4]) + "），在平台上卖有风险，请确认")
    bad = words_in(titles, COLOR_WORDS)
    if bad:
        warnings.append("标题里有颜色词（" + "、".join(bad[:4]) + "），颜色由变体管理，建议去掉")
    specs = " ".join(str(v.get("opt2_zh") or "") for v in p.get("variants") or [])
    bad = words_in(specs, [w for w in COLOR_WORDS if not re.fullmatch(r"[a-z]+", w)])
    if bad:
        warnings.append("规格名里有颜色词（" + "、".join(bad[:4]) + "），颜色请放在第一个选项「颜色」里")
    bad = words_in(allt, MARKETING_WORDS)
    if bad:
        warnings.append("文案里有营销词（" + "、".join(bad[:4]) + "），平台不允许，建议删掉")
    bad = words_in(allt, CLAIM_WORDS)
    if bad:
        warnings.append("文案里有需要证明的功能说法（" + "、".join(bad[:4]) + "），确认产品真能做到再保留")
    n_src = sum(1 for i in p.get("images") or [] if i.get("file") and i.get("from") == "source" and not i.get("edited"))
    if n_src:          # v2.50.1：选品从原站下载的图片（可能有原站水印 / logo，也可能有版权）
        warnings.append(f"还在用原站图片（{n_src} 张）：原站图片，可能有水印，建议换成自己拍的或去水印")
    why = sensitive(names + " " + str((p.get("source") or {}).get("title_original") or ""))
    if why:
        warnings.append(f"泰国市场的敏感品类：{why}，请确认能卖")
    return errors, warnings


def verify_license(pid, verified=True, force=False, who="", note=""):
    """人工核验许可证（编辑页 / 产品 360 的「核验许可」）。系统初判禁止商用的要 force。返回产品。"""
    import time
    from . import db, store
    p = store.load(pid)
    lc = p.get("license_check")
    if not lc:
        raise ValueError("这个产品没有要核验的许可")
    if verified and lc.get("auto") == "禁止商用" and not force:
        raise ValueError("系统初判这个许可证禁止商用（" + (lc.get("note") or lc.get("name") or "") + "）。确认原站许可确实允许商用（例如另外买了商用授权）再勾「仍然核验通过」")
    lc.update(status="ok" if verified else "pending", by=who if verified else "", at=time.time(), note_manual=str(note or "")[:300])
    p.setdefault("source", {})["license_verified"] = bool(verified)
    store.bump_rev(p, who)
    store.save(p)
    db.audit(who or "?", "许可核验" if verified else "取消许可核验", pid, f"{p.get('name_zh', '')}（{lc.get('name') or '原站没写许可'}）")
    return p
