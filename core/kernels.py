"""吃 CPU 的活本身（v2.20）：NAS 和电脑（worker.py）跑的是同一份代码。

NAS 上要用就调这里的「对外」函数（mesh_summary / preview_bytes / remove_bg / inpaint），它们通过 core/accel 决定在电脑上还是 NAS 上做。
电脑那边：worker.py 领到活后调用 execute(kind, params, {名字: 本地文件}, out_dir) → (结果 dict, {名字: 输出文件})。
切片比较特殊（要先在 NAS 上把打印机 / 工艺 / 耗材配置算好），在 core/slicer.orca_slice 里调 accel，执行部分是 slicer.run_cli。
"""
import os

import numpy as np

from . import accel

MESH_MIN_BYTES = 3 * 1024 * 1024        # 小于 3 MB 的模型 NAS 自己读（一两秒），传来传去反而慢
IMG_MIN_BYTES = 0


# ---------------- 算法本身（哪里跑都一样） ----------------
def _mesh_local(fp, params, thumb_path=None):
    from . import filemgr, mesh, modellib
    material = params.get("material") or "PLA"
    if params.get("loader") == "mesh":
        parts = [("model", mesh.load(fp))]
    else:
        parts = modellib.load_parts(fp)
    allt = np.concatenate([t for _n, t in parts]) if parts else np.zeros((0, 3, 3), np.float32)
    if not len(allt):
        raise ValueError("模型里没有三角面")
    out = {"metrics": filemgr.metrics(allt), "triangles": int(len(allt)), "n_parts": len(parts)}
    if params.get("orients"):
        try:
            out["orients"], out["best"] = modellib.orient_table(allt, material)
        except Exception:  # noqa: BLE001
            pass
    if params.get("parts") and len(parts) > 1:
        pl = []
        for i, (n, t) in enumerate(parts[:60]):
            row = {"index": i, "name": str(n)[:60], "metrics": filemgr.metrics(t), "triangles": int(len(t))}
            if params.get("orients"):
                try:
                    row["orients"], row["best"] = modellib.orient_table(t, material)
                except Exception:  # noqa: BLE001
                    pass
            pl.append(row)
        out["parts"] = pl
    if thumb_path:
        try:
            modellib.render_thumb(allt, thumb_path)
            out["thumb"] = True
        except Exception:  # noqa: BLE001  缩略图画不出来不影响
            pass
    return out


def _preview_local(fp, params):
    from . import filemgr, preview
    return preview._make(fp, filemgr.metrics, int(params.get("target") or preview.TARGET))


def _img_open(path):
    from PIL import Image
    im = Image.open(path)
    im.load()
    return im


def execute(kind, params, files, out_dir):
    """电脑上执行一件活。返回 (结果, {名字: 输出文件路径})。文件本身的问题抛 ValueError（NAS 不再重试），缺组件抛 RuntimeError（NAS 改自己做）。"""
    if kind == "mesh":
        thumb = os.path.join(out_dir, "thumb.png") if params.get("thumb") else None
        res = _mesh_local(files["model"], params, thumb)
        return res, ({"thumb": thumb} if thumb and res.get("thumb") else {})
    if kind == "preview":
        p = os.path.join(out_dir, "preview.bin.gz")
        with open(p, "wb") as f:
            f.write(_preview_local(files["model"], params))
        return {"ok": True}, {"preview": p}
    if kind == "slice":
        from . import slicer
        exe = _orca()
        if not exe:
            raise RuntimeError("这台电脑上没有找到 OrcaSlicer")
        keep = os.path.join(out_dir, "kept.3mf") if params.get("keep") else None
        try:
            res = slicer.run_cli(exe, files["machine"], files["process"], files["filament"], files["model"], out_dir + "/work",
                                 params, keep, model_name=params.get("model_name") or "")
        except slicer.SliceError as e:
            raise ValueError(str(e)) from e
        return res, ({"kept": keep} if keep and os.path.exists(keep) else {})
    if kind == "toolpath":
        from . import toolpath
        p = os.path.join(out_dir, "toolpath.gz")
        zs, chunks = toolpath.parse(toolpath.read_gcode(files["file"], params.get("kind") or "3mf"))
        with open(p, "wb") as f:
            f.write(toolpath.encode(zs, chunks))
        return {"ok": True}, {"toolpath": p}
    if kind == "removebg":
        from . import imgtools
        out = imgtools._remove_bg_local(_img_open(files["image"]), params.get("model") or "isnet")
        p = os.path.join(out_dir, "out.png")
        out.save(p)
        return {"ok": True}, {"image": p}
    if kind == "inpaint":
        from . import imgtools
        out, used = imgtools._inpaint_local(_img_open(files["image"]), _img_open(files["mask"]), params.get("method") or "auto")
        p = os.path.join(out_dir, "out.png")
        out.save(p)
        return {"method": used, "mode": out.mode}, {"image": p}
    raise RuntimeError(f"不认识的任务：{kind}")


ORCA_PATH = ""      # 电脑上的 OrcaSlicer 位置（worker.json 里可以指定；空 = 自动找）


def _orca():
    from . import slicer
    from .config import load_config
    cfg = dict(load_config())
    if ORCA_PATH:
        cfg["orca_path"] = ORCA_PATH
    return slicer.find_orca(cfg)


def capabilities():
    """这台电脑能做哪些活（worker.py 报到时用）。返回 (caps, info)；info["missing"] = {活: 为什么做不了、怎么办}。"""
    import importlib
    importlib.invalidate_caches()
    caps = ["mesh", "preview", "toolpath"]
    info = {"missing": {}}
    try:
        exe = _orca()
        if exe:
            caps.append("slice")
            info["orca"] = exe
        else:
            info["missing"]["slice"] = "这台电脑上没找到 OrcaSlicer：装 OrcaSlicer（orcaslicer.com）后重启加速程序；装在别的位置可以在 data/worker.json 里填 orca_path"
    except Exception as e:  # noqa: BLE001
        info["missing"]["slice"] = f"找 OrcaSlicer 出错：{e}"
    try:
        from . import imgtools
        st = imgtools.status()
        if st.get("rembg"):
            caps.append("removebg")
        else:
            info["missing"]["removebg"] = "抠图组件还没装好（加速程序会自动安装，约 200 MB，装好后自动开始帮忙）"
        caps.append("inpaint")
        info["inpaint"] = st.get("inpaint")
    except Exception as e:  # noqa: BLE001
        info["missing"]["removebg"] = f"抠图组件出错：{e}"
    return caps, info


# ---------------- NAS 上调用的 ----------------
def mesh_summary(fp, material="PLA", loader="parts", orients=True, parts=True, thumb_to=None, err_cls=ValueError):
    """读模型：尺寸 / 体积 / 面数 / 摆放方向 / 各零件（可选缩略图写到 thumb_to）。大文件交给电脑。"""
    params = {"material": material, "loader": loader, "orients": orients, "parts": parts, "thumb": bool(thumb_to)}

    def done(res, out):
        if thumb_to and out.get("thumb"):
            import shutil
            shutil.copyfile(out["thumb"], thumb_to)
        elif thumb_to:
            res.pop("thumb", None)
        return res
    return accel.run("mesh", params, {"model": fp}, lambda: _mesh_local(fp, params, thumb_to), done,
                     timeout=900, min_bytes=MESH_MIN_BYTES, err_cls=err_cls)


def preview_bytes(fp, target):
    params = {"target": target}

    def done(_res, out):
        with open(out["preview"], "rb") as f:
            return f.read()
    from . import preview
    return accel.run("preview", params, {"model": fp}, lambda: _preview_local(fp, params), done,
                     timeout=900, min_bytes=max(MESH_MIN_BYTES, preview.SYNC_BYTES), err_cls=ValueError)


def toolpath_blob(path, kind):
    """切好的文件 → 3D 切片预览数据（读整个 G-code，大文件很吃 CPU：交给电脑）。"""
    from . import toolpath

    def local():
        return toolpath.encode(*toolpath.parse(toolpath.read_gcode(path, kind)))

    def done(_res, out):
        with open(out["toolpath"], "rb") as f:
            return f.read()
    return accel.run("toolpath", {"kind": kind}, {"file": path}, local, done, timeout=900, min_bytes=MESH_MIN_BYTES,
                     err_cls=ValueError)
