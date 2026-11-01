"""桌面客户端「🔧 切片软件自检」的服务器端（v2.56，T36）。

老板的电脑不能远程控制，Windows 上 Bambu Studio / OrcaSlicer 能不能用要靠他自己点一次自检：
start() 生成一个自检用的测试盘（两个方块、两槽多色；不建产品、不碰正式数据），Bambu 版和 Orca 版各一份 →
桌面客户端用软件打开 → 人在软件里随便挪一下零件、Ctrl+S → 自动回传 → check() 核对零件编号 / 位置 / 槽 / 颜色 / 配置 →
客户端汇总成通过 / 不通过清单 → report() 存日志（最近 20 次），设置 → 组件与插件 的桌面客户端卡片里能看「最近一次自检」。
测试文件一天后自动清理（报告后马上清理）。
"""
import json
import os
import secrets
import threading
import time

import numpy as np

from core.config import DATA_DIR, load_config

DIR = os.path.join(DATA_DIR, "slicer_edit", "selftest")
LOG = os.path.join(DATA_DIR, "desktop_selftest.json")
KEEP_S = 86400
_lock = threading.Lock()
SLOTS = [{"slot": 1, "material": "PLA", "hex": "#F4F4F2"}, {"slot": 2, "material": "PLA", "hex": "#202124"}]
OBJS = [("selftest-A", 1, 80.0, 100.0, 20.0), ("selftest-B", 2, 170.0, 100.0, 15.0)]     # (编号, 槽, x, y, 边长)


def _cube(s):
    v = np.array([[0, 0, 0], [s, 0, 0], [s, s, 0], [0, s, 0], [0, 0, s], [s, 0, s], [s, s, s], [0, s, s]], float) - [s / 2, s / 2, 0]
    t = np.array([(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)])
    return v, t


def _load():
    try:
        with open(os.path.join(DIR, "sessions.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    os.makedirs(DIR, exist_ok=True)
    p = os.path.join(DIR, "sessions.json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(p + ".tmp", p)


def cleanup(now=None, drop=()):
    now = now or time.time()
    with _lock:
        d = _load()
        for sid in [k for k, v in d.items() if now - v["created"] > KEEP_S or k in drop]:
            d.pop(sid, None)
            for ext in (".3mf", ".up.3mf"):
                try:
                    os.remove(os.path.join(DIR, sid + ext))
                except OSError:
                    pass
        _save(d)


def _printer_for(app, cfg):
    from core import fleet
    for p in cfg.get("printers") or []:
        if fleet.tech_of(p) != "resin" and fleet.slicer_app_of(p, cfg) == app:
            return p.get("name")
    return "Bambu Lab P1S" if app == "bambu" else "Creality K1C"


def start(user="", apps=("bambu", "orca")):
    """两个软件各生成一份测试盘项目 3MF。返回 {app: {sid, download, upload, filename, printer}}。"""
    from modules.model import slicerproj as sp
    cleanup()
    cfg = load_config()
    out = {}
    for app in apps:
        if app not in sp.APPS:
            continue
        printer = _printer_for(app, cfg)
        plate = {"id": "selftest", "printer": printer, "layer_height": 0.2, "slots": [dict(s, colour="") for s in SLOTS], "items": [], "params": {}}
        objs = []
        for uid, slot, x, y, s in OBJS:
            v, t = _cube(s)
            objs.append({"name": sp.obj_name(f"Test {uid[-1]}", uid.replace("-", "")), "x": x, "y": y, "rot": 0, "extruder": slot,
                         "ov": [], "parts": [{"name": sp.part_name(f"Test {uid[-1]}", uid.replace("-", ""), 0), "v": v, "t": t, "attrs": None,
                                              "extruder": slot, "subtype": "normal_part"}]})
        settings, notes = sp.project_settings(cfg, {"material": "PLA"}, plate, [{"material": s["material"], "hex": s["hex"]} for s in SLOTS], app)
        sid = "st" + secrets.token_hex(6)
        os.makedirs(DIR, exist_ok=True)
        sp.write_project(os.path.join(DIR, sid + ".3mf"), objs, app, settings)
        tok, dl = secrets.token_urlsafe(20), secrets.token_urlsafe(16)
        with _lock:
            d = _load()
            d[sid] = {"app": app, "user": user, "created": time.time(), "token": tok, "dl": dl, "printer": printer,
                      "settings": bool(settings), "notes": notes, "check": None}
            _save(d)
        out[app] = {"sid": sid, "app": app, "download": f"/api/desktop/st/{sid}/file?t={dl}", "upload": f"/api/desktop/st/{sid}/upload?t={tok}",
                    "filename": f"3D-Ops-selftest-{'BambuStudio' if app == 'bambu' else 'Orca'}.3mf", "folder": "selftest", "printer": printer,
                    "notes": notes}
    return out


def take_file(sid, tok):
    with _lock:
        d = _load()
        s = d.get(sid)
        if not s or not tok or not secrets.compare_digest(s.get("dl") or "", str(tok)):
            raise PermissionError("自检下载地址过期了")
        s["dl"] = ""
        _save(d)
    return os.path.join(DIR, sid + ".3mf"), f"3D-Ops-selftest-{'BambuStudio' if s['app'] == 'bambu' else 'Orca'}.3mf"


def check(rp, expect_slots=None):
    """核对软件保存回来的测试盘（read_project 的结果）。纯函数。"""
    want = {uid.replace("-", ""): (slot, x, y) for uid, slot, x, y, _s in OBJS}
    got = {o["uid"]: o for o in rp.get("objects") or [] if o["uid"] in want}
    out = {"objects_ok": len(got) == len(want) and len(rp.get("objects") or []) >= len(want),
           "objects_detail": f"{len(got)}/{len(want)}：" + ", ".join(sorted(got))}
    moved = []
    for u, o in got.items():
        v = np.asarray(o["world"]).reshape(-1, 3)
        c = (v.min(0) + v.max(0)) / 2
        if abs(c[0] - want[u][1]) > 0.5 or abs(c[1] - want[u][2]) > 0.5:
            moved.append(f"{u} → ({c[0]:.1f}, {c[1]:.1f})")
    out["moved"], out["moved_detail"] = bool(moved), "；".join(moved) or "两个零件都在原位（软件里没挪？）"
    slots = {u: o["extruder"] for u, o in got.items()}
    out["slots_ok"] = all(slots.get(u) == want[u][0] for u in got) and bool(got)
    out["slots_detail"] = ", ".join(f"{u}: {slots[u]}" for u in sorted(slots))
    hexes = [f.get("hex", "").upper() for f in rp.get("filaments") or []]
    exp = expect_slots or [s["hex"] for s in SLOTS]
    out["colours_ok"] = hexes[:len(exp)] == [h.upper() for h in exp]
    out["colours_detail"] = " ".join(hexes) or "文件里没有耗材列表"
    out["settings_ok"] = bool(rp.get("printer_profile"))
    out["settings_detail"] = rp.get("printer_profile") or "文件里没有打印机配置"
    out["app_ver"] = rp.get("app_ver") or ""
    out["application"] = rp.get("application") or ""
    return out


def upload(sid, tok, data):
    from modules.model import editsession, slicerproj as sp
    with _lock:
        s = _load().get(sid)
    if not s or not tok or not secrets.compare_digest(s.get("token") or "", str(tok)):
        raise PermissionError("自检会话不对或已结束")
    editsession.valid_project(data)
    with open(os.path.join(DIR, sid + ".up.3mf"), "wb") as f:
        f.write(data)
    res = check(sp.read_project(data))
    with _lock:
        d = _load()
        if sid in d:
            d[sid]["check"] = res
            _save(d)
    return res


def report(user, data):
    """客户端汇总的结果存日志（最近 20 次），自检文件清理掉。"""
    from core import db
    rec = {"at": time.time(), "user": user, "pc": str(data.get("pc") or "")[:40], "client": str(data.get("client") or "")[:20],
           "slicers": {k: ({"version": str((v or {}).get("version") or "")[:40], "path": str((v or {}).get("path") or "")[:200]} if v else None)
                       for k, v in (data.get("slicers") or {}).items() if k in ("bambu", "orca")},
           "checks": [{"key": str(c.get("key"))[:40], "ok": bool(c.get("ok")), "zh": str(c.get("zh"))[:120], "th": str(c.get("th"))[:160],
                       "detail": str(c.get("detail") or "")[:300]} for c in (data.get("checks") or [])[:40]],
           "errors": [str(x)[:300] for x in (data.get("errors") or [])[:10]]}
    rec["passed"] = bool(rec["checks"]) and all(c["ok"] for c in rec["checks"])
    with _lock:
        try:
            with open(LOG, encoding="utf-8") as f:
                log = json.load(f)
        except (OSError, ValueError):
            log = []
        log = [rec] + log[:19]
        with open(LOG + ".tmp", "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False)
        os.replace(LOG + ".tmp", LOG)
    cleanup(drop=set(data.get("sids") or []))
    bad = [c["zh"] for c in rec["checks"] if not c["ok"]]
    db.audit(user, "切片软件自检", rec["pc"], ("通过" if rec["passed"] else "不通过：" + "；".join(bad))[:300])
    return rec


def log():
    try:
        with open(LOG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []
