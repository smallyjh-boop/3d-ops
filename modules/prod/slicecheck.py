"""切片文件和打印机核对（v2.32）：发到打印机前，切片文件必须是这台机型的，否则会撞喷嘴、撞热床、温度不对，损坏机器。

核对三样（任何一样对不上都不让发，没有强行发送的口子）：
  机型   切片文件里的打印机配置名（Bambu Studio / Orca 的 printer_settings_id / printer_model）
         光固化文件按扩展名认机型；认不出来的文件要老板先「确认机型」一次
  喷嘴   文件的喷嘴直径 和 打印机设置里的喷嘴直径（没填按 0.4）
  热床板 打印机设置里填了「现在装的热床板」才核对（没填不核对，只在开始对话框里提醒）
对外：file_model(f)  check(f, idx)  describe(f)  confirm(fid, printer_name, user)
"""
import json
import re

from core import db
from core.config import load_config

PLATE_ZH = {"cool plate": "低温板", "engineering plate": "工程板", "high temp plate": "高温板", "textured pei plate": "纹理 PEI 板",
            "smooth pei plate": "光面 PEI 板", "supertack plate": "超粘板"}


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _known_models(cfg=None):
    """所有能认的机型名：设置里的打印机（机型名、Orca 机器名）+ 常用机型表。返回 [(规范化的名字, 机型名)]。"""
    from core import fleet
    cfg = cfg or load_config()
    out = []
    for p in cfg.get("printers") or []:
        p = fleet.effective(p, cfg)           # v2.54：机型模板 + 单台覆盖
        for n in (p.get("name"), p.get("orca_machine")):
            if n:
                out.append((_norm(n), p.get("name")))
    for m in fleet.MODELS:
        out.append((_norm(m["name"]), m["name"]))
    return out


def model_of_profile(profile, cfg=None):
    """切片文件里的打印机配置名 → 机型名（最长、按整词匹配的那个）。认不出返回 None。"""
    prof = _norm(profile)
    if not prof:
        return None
    best = None
    for n, name in _known_models(cfg):
        if not n:
            continue
        hit = n == prof or re.search(r"(^| )" + re.escape(n) + r"( |$)", prof) or re.search(r"(^| )" + re.escape(prof) + r"( |$)", n)
        if hit:
            score = len(n) + (1000 if n == prof else 0)
            if not best or score > best[0]:
                best = (score, name)
    return best[1] if best else None


def file_model(f, cfg=None):
    """这个切片文件是哪个机型的。返回 (机型名或 None, 来源说明)。"""
    rp = (f or {}).get("report") or {}
    if rp.get("confirmed_printer"):
        return rp["confirmed_printer"], f"{rp.get('confirmed_by') or '老板'}确认"
    if (f or {}).get("kind") == "resin":
        from core import resinfile
        m = resinfile.model_from_ext(f.get("filename") or "")
        return (m, "按文件类型") if m else (None, "")
    prof = (rp.get("params") or {}).get("printer_profile")
    m = model_of_profile(prof, cfg)
    return (m, "文件里读出") if m else (None, "")


def _same_model(a, b, p=None):
    if not a or not b:
        return False
    if _norm(a) == _norm(b):
        return True
    return bool(p and p.get("orca_machine") and model_of_profile(p.get("orca_machine")) == a and p.get("name") == b)


def check(f, idx, cfg=None):
    """返回 {ok, errors: [中文], need_confirm, file_model, printer_model, nozzle, plate}。"""
    from core import fleet
    cfg = cfg or load_config()
    prs = cfg.get("printers") or []
    out = {"ok": True, "errors": [], "need_confirm": False, "file_model": None, "printer_model": None}
    if not f:
        return out
    if idx is None or not (0 <= int(idx) < len(prs)):
        out.update(ok=False, errors=["没有选打印机"])
        return out
    p = fleet.effective(prs[int(idx)], cfg)    # v2.54：喷嘴 / 热床板 / Orca 配置按机型模板 + 这台的单独设置
    pname = p.get("name") or ""
    out["printer_model"] = pname
    code = p.get("code") or f"#{int(idx) + 1}"
    # 1. FDM / 光固化
    if (f.get("kind") == "resin") != (fleet.tech_of(p) == "resin"):
        out["errors"].append(f"这是{'光固化' if f.get('kind') == 'resin' else 'FDM'}切片文件，「{code} {pname}」是"
                             f"{'光固化' if fleet.tech_of(p) == 'resin' else 'FDM'}打印机")
    # 2. 机型
    fm, src = file_model(f, cfg)
    out["file_model"], out["model_source"] = fm, src
    if f.get("printer") not in (None, "", "*") and not _same_model(f.get("printer"), pname, p):
        out["errors"].append(f"这个文件登记的是「{f['printer']}」用的，不能发到「{code} {pname}」")
    if not fm:
        out["need_confirm"] = True
        out["errors"].append("认不出这个切片文件是哪台机型切的（文件里没有打印机信息）。请老板在文件卡片上点「确认机型」后再用")
    elif not _same_model(fm, pname, p):
        out["errors"].append(f"机型不对：这是「{fm}」的切片文件，不能发到「{code} {pname}」——会损坏机器。请用这台机型重新切片")
    # 3. 喷嘴
    prm = (f.get("report") or {}).get("params") or {}
    if f.get("kind") != "resin":
        try:
            want = float(p.get("nozzle") or 0.4)
        except (TypeError, ValueError):
            want = 0.4
        have = prm.get("nozzle_mm")
        out["nozzle"] = {"file": have, "printer": want}
        if have and abs(float(have) - want) > 0.01:
            out["errors"].append(f"喷嘴不对：切片文件是 {have} mm 喷嘴，「{code}」装的是 {want} mm（在 设置 → 生产 → 打印机 里改）")
        # 4. 热床板（打印机设置里填了才核对）
        plate = _norm(p.get("plate"))
        fplate = _norm(prm.get("bed_type"))
        out["plate"] = {"file": prm.get("bed_type_zh") or prm.get("bed_type"), "printer": PLATE_ZH.get(plate, p.get("plate") or "")}
        if plate and fplate and plate != fplate:
            out["errors"].append(f"热床板不对：切片文件用的是「{PLATE_ZH.get(fplate, prm.get('bed_type'))}」，"
                                 f"「{code}」现在装的是「{PLATE_ZH.get(plate, p.get('plate'))}」")
    out["ok"] = not out["errors"]
    return out


def describe(f, cfg=None):
    """给文件卡片显示：这个文件能发到哪几台打印机。"""
    cfg = cfg or load_config()
    fm, src = file_model(f, cfg)
    ok_for = []
    for i, p in enumerate(cfg.get("printers") or []):
        if check(f, i, cfg)["ok"]:
            ok_for.append(p.get("code") or f"#{i + 1}")
    prm = ((f or {}).get("report") or {}).get("params") or {}
    return {"model": fm, "source": src, "need_confirm": not fm, "ok_for": ok_for,
            "nozzle": prm.get("nozzle_mm"), "plate": prm.get("bed_type_zh") or prm.get("bed_type"),
            "profile": prm.get("printer_profile") or ""}


def confirm(fid, printer_name, user=""):
    """老板确认「这个文件是给哪台机型的」（文件里读不出机型时）。只能确认成设置里有的机型。"""
    from core import print_files
    f = print_files.get(int(fid))
    if not f:
        raise ValueError("文件不存在")
    names = [p.get("name") for p in load_config().get("printers") or []]
    if printer_name not in names:
        raise ValueError("请选设置里有的打印机机型")
    fm, src = file_model(f)
    if fm and src != f"{(f.get('report') or {}).get('confirmed_by') or '老板'}确认" and fm != printer_name:
        raise ValueError(f"文件里写着是「{fm}」的切片，不能改成「{printer_name}」。请用这台机型重新切片")
    rp = dict(f.get("report") or {})
    rp["confirmed_printer"], rp["confirmed_by"] = printer_name, user
    c = db.conn()
    c.execute("UPDATE print_files SET report=?, printer=? WHERE id=?", (json.dumps(rp, ensure_ascii=False), printer_name, f["id"]))
    c.commit()
    db.audit(user, "确认切片文件机型", f"#{f['id']} {f.get('filename')}", printer_name)
    return print_files.get(f["id"])
