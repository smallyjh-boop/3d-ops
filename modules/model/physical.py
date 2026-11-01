"""实物数据（v2.55.1 T31）的自动值：成品尺寸按模型 / 组装外框，净重按打印方案切片（扣支撑、扣换色冲刷）。
数据结构、确认状态、导出拦截在 core/physical.py。

尺寸：单零件 → 模型外框（src=model）；多零件 → 组装视图里组装好的外框（src=assembly）；
      多零件但没组装过 → 不自动填（多零件文件的外框是平铺排版的，不是成品尺寸），提示人工量。
包裹：能装下成品的最小邮政纸箱（src=box）；没有合适的 → 成品尺寸每边 +1.5 cm（src=est）。
净重：打印方案每一盘都切过片 → 每盘（不含冲刷；有无支撑切片结果时用无支撑的）÷ 每盘套数，合计一套（src=slice）。
      成本、扣库存仍用变体的克数（含支撑、冲刷），不走这里。
所有自动值都是「待确认」。
"""
import numpy as np

from core import physical as ph
from core import store
from core.config import load_config

from . import assembly as asm
from . import printplan as pp


def _info_of(p, eid, part):
    e = next((x for x in p.get("model_lib") or [] if x.get("id") == eid), None) or {}
    info = e.get("info") or {}
    if part in (None, ""):
        return info
    return next((x for x in info.get("parts") or [] if x.get("index") == int(part)), None) or {}


def auto_size(pid, spec="", p=None):
    """这个规格的成品尺寸（毫米）。返回 {v: [宽, 深, 高], src, vol_cm3, parts} 或 {need: assemble / nomodel, parts}。"""
    p = p or store.load(pid)
    r = asm.resolve(p, spec)
    inst = [(k, it) for k, it, _n in asm.instances(r["items"]) if not (r["poses"].get(k) or {}).get("hidden")]
    if not inst:
        return {"need": "nomodel", "parts": 0}
    k = float(r.get("scale") or 1.0)
    vol = 0.0
    for _k, it in inst:
        vol += float(_info_of(p, it["id"], it.get("part")).get("volume_cm3") or 0) * k ** 3
    vol = round(vol, 2) or None
    if len(inst) == 1 and not r["poses"]:
        info = _info_of(p, inst[0][1]["id"], inst[0][1].get("part"))
        s = info.get("size")
        if s and len(s) == 3:
            return {"v": [round(float(x) * k, 1) for x in s], "src": "model", "vol_cm3": vol, "parts": 1}
    if len(inst) > 1 and not r["poses"]:
        return {"need": "assemble", "parts": len(inst)}
    t = asm._assemble(pid, p, r)
    if t is None:
        return {"need": "nomodel", "parts": 0}
    v = np.asarray(t).reshape(-1, 3)
    size = v.max(0) - v.min(0)
    return {"v": [round(float(x), 1) for x in size], "src": "model" if len(inst) == 1 else "assembly", "vol_cm3": vol, "parts": len(inst)}


def _infill(p, spec):
    try:
        plan = pp.get_plan(p, pp.plan_key(p, spec))
        pl = next((x for x in plan.get("plates") or [] if x.get("items")), None)
        if pl:
            return float((pp.recipe_of(p, pl) or {}).get("infill_pct") or 15)
    except (ValueError, OSError, KeyError, TypeError):
        pass
    return float((p.get("recipe") or {}).get("infill_pct") or 15)


def fill_size(pid, specs=None, user="", force=False):
    """「📏 按组装尺寸填入」：每个规格的成品尺寸 + 包裹尺寸（纸箱），都待确认。
    返回 {spec: {ok, v, src, box, pkg} 或 {need}}。"""
    p = store.load(pid)
    cfg = load_config()
    keys = ph.spec_keys(p)
    out = {}
    for s in keys if specs is None else [x for x in keys if x in specs]:
        a = auto_size(pid, s, p)
        if a.get("need"):
            out[s] = a
            continue
        ph.set_extra(p, s, cfg, vol_cm3=a.get("vol_cm3"), infill=_infill(p, s))
        wrote = ph.set_item(p, s, "size", a["v"], a["src"], user, None, force, cfg)
        pkg, box, src = ph.auto_pkg(a["v"])
        pw = False
        if pkg:
            if src == "box":
                cur = ph.row(p, s, cfg)["pkg"]
                if force or ph.SRC_RANK.get(cur["src"], 0) < ph.SRC_RANK["box"] or not cur["v"]:
                    ph.set_box(p, s, box, user, cfg, auto=True)
                    pw = True
            else:
                pw = ph.set_item(p, s, "pkg", pkg, "est", user, None, force, cfg)
                if pw:
                    ph._st(p, s)["box"] = ""
                    ph._mirror(p, s)
        if s == keys[0] and (force or not (p.get("size_text") or "").strip()):
            cm = [x / 10 for x in a["v"]]
            p["size_text"] = " × ".join(f"{round(x, 1):g}" for x in cm) + " cm"
        out[s] = {"ok": True, "v": a["v"], "src": a["src"], "size_written": wrote, "pkg_written": pw, "pkg": pkg, "box": box}
    store.save(p)
    return out


def plan_net(p, spec):
    """按打印方案的切片结果算一套成品的净重（克）：每盘（不含冲刷；有无支撑结果用无支撑的）÷ 套数 合计。
    有没切过的盘 → None。返回 {v, nosup: 是不是每盘都扣了支撑, plates}。"""
    key = pp.plan_key(p, spec)
    plan = pp.get_plan(p, key)
    plates = [pl for pl in plan.get("plates") or [] if pl.get("items")]
    if not plates:
        return None
    tot, nosup = 0.0, True
    for pl in plates:
        sl = pl.get("sliced") or {}
        if not (sl.get("filaments") or sl.get("grams")):
            return None
        if sl.get("nosup_g") is not None and not sl.get("trial"):
            g = float(sl["nosup_g"])
        else:
            nosup = False
            if sl.get("filaments"):
                g = sum(float(f.get("grams") or 0) for f in sl["filaments"])      # 记的已经是扣了冲刷的
            else:
                g = float(sl.get("grams") or 0) - float(sl.get("purge_g") or 0)
        tot += max(0.0, g) / max(1, int(pl.get("sets") or 1))
    return {"v": round(tot, 1), "nosup": nosup, "plates": len(plates)} if tot > 0 else None


def update_net(pid, specs=None, user=""):
    """按切片结果写净重（src=slice，待确认；实称 / 手填的不覆盖）。返回 {spec: {v, nosup, written} 或 None}。"""
    p = store.load(pid)
    cfg = load_config()
    out = {}
    for s in ph.spec_keys(p):
        if specs is not None and s not in specs:
            continue
        n = plan_net(p, s)
        if not n:
            out[s] = None
            continue
        w = ph.set_item(p, s, "net", n["v"], "slice", user, None, False, cfg, note=None if n["nosup"] else "with_support")
        out[s] = dict(n, written=w)
    store.save(p)
    return out


def slice_and_net(pid, user=""):
    """「✂ 切片算重量」：打印方案一键全部切片（printplan.slice_all 最后会写净重），返回切片结果 + 每个规格的净重。"""
    r = pp.slice_all(pid, user)
    r["net"] = update_net(pid, None, user)
    return r


def view(pid, p=None):
    """给编辑页 / 上架工作台：每个规格一行（值、来源、状态、检查）+ 自动尺寸能不能填（不读模型文件）。"""
    p = p or store.load(pid)
    cfg = load_config()
    rows = ph.rows(p, cfg)
    out = []
    for s, r in rows.items():
        try:
            rs = asm.resolve(p, s)
            inst = [k for k, _it, _n in asm.instances(rs["items"]) if not (rs["poses"].get(k) or {}).get("hidden")]
            r["parts"] = len(inst)
            r["assembled"] = bool(rs["poses"])
        except Exception:  # noqa: BLE001  模型库有问题也要能看实物数据
            r["parts"], r["assembled"] = 0, False
        try:
            r["plan_net"] = plan_net(p, s)
        except Exception:  # noqa: BLE001
            r["plan_net"] = None
        out.append(r)
    from core.inventory import boxes
    return {"specs": out, "boxes": boxes.catalog(), "filler_g": float(cfg.get("filler_weight_g", 20) or 0),
            "packaging_g": float(cfg.get("packaging_weight_g", 50) or 0), "blocking": ph._blocking(cfg),
            "mirror": {"package": p.get("package"), "package_status": p.get("package_status"), "pack_box": p.get("pack_box"),
                       "size_text": p.get("size_text")}}
