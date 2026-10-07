"""修图工具（v2.14）：去背景、去水印 / 去杂物（局部修复）。都在本机运行，不用 AI 接口。

去背景：rembg（isnet 通用模型；可选 BiRefNet，边缘更细，速度慢一些）。
去水印：有 LaMa 模型（开源，约 200MB，系统检查页一键下载）就用 LaMa，效果最好；
        没有就用 OpenCV 的修复算法（适合小面积文字 / 水印 / 杂点）；都没有用简单的扩散填充。
只处理涂抹区域附近的一块，原图其他地方像素不变，大图也不会变糊。
"""
import base64
import io
import os
import threading
import time

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .config import DATA_DIR

LAMA_URL = "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx"
LAMA_DIR = os.path.join(DATA_DIR, ".runtime", "lama")
LAMA_PATH = os.path.join(LAMA_DIR, "lama_fp32.onnx")
LAMA_SIZE = 512
BG_MODELS = {"isnet": "isnet-general-use", "birefnet": "birefnet-general"}
MAX_SIDE = 4096

_sessions = {}
_lama = None
_lock = threading.Lock()
LAMA_JOB = {}


# ---------------- 图片编码 ----------------
def from_data_url(s):
    if not s:
        raise ValueError("没有图片")
    if "," in s[:100]:
        s = s.split(",", 1)[1]
    try:
        img = Image.open(io.BytesIO(base64.b64decode(s)))
        img = ImageOps.exif_transpose(img)
        img.load()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"图片读不了：{e}") from e
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return img


def to_data_url(img, fmt="PNG"):
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=92)
        mime = "image/jpeg"
    else:
        img.save(buf, "PNG", optimize=False)
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


# ---------------- 组件状态 ----------------
def _has(mod):
    import importlib.util
    return importlib.util.find_spec(mod) is not None


def status():
    return {"rembg": _has("rembg"), "birefnet": _has("rembg"), "cv2": _has("cv2"), "onnxruntime": _has("onnxruntime"),
            "lama": os.path.exists(LAMA_PATH) and _has("onnxruntime"), "lama_job": dict(LAMA_JOB),
            "inpaint": "lama" if (os.path.exists(LAMA_PATH) and _has("onnxruntime")) else "opencv" if _has("cv2") else "basic"}


# ---------------- 去背景 ----------------
def remove_bg(img, model="isnet"):
    """去背景。电脑在线时交给电脑做（v2.20，电脑有显卡更快），不然 NAS 自己做。"""
    return _via_pc("removebg", {"model": model}, {"image": img}, lambda: _remove_bg_local(img, model),
                   lambda res, out: _open(out["image"]).convert("RGBA"))


def _open(path):
    im = Image.open(path)
    im.load()
    return im


def _via_pc(kind, params, imgs, local, done):
    """把 PIL 图存成临时 PNG，交给 core/accel。"""
    import shutil
    import tempfile
    from . import accel
    if not accel.enabled():
        with accel.heavy():
            return local()
    d = tempfile.mkdtemp(prefix="imgpc_")
    try:
        files = {}
        for k, im in imgs.items():
            files[k] = os.path.join(d, k + ".png")
            im.save(files[k])
        return accel.run(kind, params, files, local, done, timeout=600, err_cls=ValueError)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _remove_bg_local(img, model="isnet"):
    if os.environ.get("LH_DOCKER") == "1":
        os.environ.setdefault("U2NET_HOME", os.path.join(DATA_DIR, ".runtime", "u2net"))
    try:
        from rembg import new_session, remove
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("去背景组件没有安装：系统 →「系统检查与升级」→ 抠图组件 → 点「安装」") from e
    name = BG_MODELS.get(model, BG_MODELS["isnet"])
    with _lock:
        if name not in _sessions:
            try:
                _sessions[name] = new_session(name)
            except Exception as e:  # noqa: BLE001
                if name != BG_MODELS["isnet"]:
                    raise RuntimeError(f"精细抠图模型用不了（{e}）。可以先用「标准」模型") from e
                raise
        sess = _sessions[name]
    out = remove(img.convert("RGB"), session=sess)
    return out.convert("RGBA")


# ---------------- 去水印 / 去杂物 ----------------
def _mask_bbox(mask, pad):
    a = np.asarray(mask) > 127
    ys, xs = np.where(a)
    if not len(xs):
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    w, h = mask.size
    side = int(max(x1 - x0, y1 - y0) + pad * 2)
    side = max(side, 96)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    side = min(side, max(w, h))
    bx = int(min(max(0, cx - side // 2), max(0, w - side)))
    by = int(min(max(0, cy - side // 2), max(0, h - side)))
    return bx, by, min(w, bx + side), min(h, by + side)


def _lama_session():
    global _lama
    if _lama is None:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
        _lama = ort.InferenceSession(LAMA_PATH, sess_options=so, providers=["CPUExecutionProvider"])
    return _lama


def _inpaint_lama(rgb, m):
    """rgb: 小块图（PIL RGB），m: 同尺寸的 L 遮罩。缩到 512 跑 LaMa，再放大回去。"""
    sess = _lama_session()
    S = LAMA_SIZE
    im = np.asarray(rgb.resize((S, S), Image.BICUBIC), dtype=np.float32) / 255.0
    mk = (np.asarray(m.resize((S, S), Image.NEAREST), dtype=np.float32) > 127).astype(np.float32)
    names = [i.name for i in sess.get_inputs()]
    feeds = {names[0]: im.transpose(2, 0, 1)[None], names[1]: mk[None, None]}
    out = sess.run(None, feeds)[0][0].transpose(1, 2, 0)
    if out.max() <= 1.5:      # 有的导出版本输出 0-1
        out = out * 255.0
    res = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    return res.resize(rgb.size, Image.BICUBIC)


def _inpaint_cv2(rgb, m):
    import cv2
    a = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
    mk = (np.asarray(m) > 127).astype(np.uint8) * 255
    r = max(3, int(round(max(rgb.size) / 150)))
    out = cv2.inpaint(a, mk, r, cv2.INPAINT_TELEA)
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))


def _inpaint_basic(rgb, m):
    """没有 OpenCV 时：从边缘往里一圈圈用周围颜色填（只适合很小的点）。"""
    a = np.asarray(rgb, dtype=np.float32).copy()
    hole = np.asarray(m) > 127
    for _ in range(400):
        if not hole.any():
            break
        known = ~hole
        acc = np.zeros_like(a)
        cnt = np.zeros(hole.shape, np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            k = np.roll(np.roll(known, dy, 0), dx, 1)
            v = np.roll(np.roll(a, dy, 0), dx, 1)
            acc += v * k[..., None]
            cnt += k
        fill = hole & (cnt > 0)
        a[fill] = acc[fill] / cnt[fill][:, None]
        hole = hole & ~fill
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def inpaint(img, mask, method="auto"):
    """img: PIL 图；mask: PIL（白 = 要去掉的地方）。返回 (结果图, 用的方法)。电脑上方法一样好或更好时交给电脑做（v2.20）。"""
    if not _mask_bbox(mask.convert("L"), 1):
        raise ValueError("先用画笔涂出要去掉的地方")

    def done(res, out):
        im = _open(out["image"])
        return (im.convert("RGBA") if res.get("mode") == "RGBA" else im.convert("RGB")), res.get("method") or "pc"
    return _via_pc("inpaint", {"method": method}, {"image": img, "mask": mask}, lambda: _inpaint_local(img, mask, method), done)


def _inpaint_local(img, mask, method="auto"):
    """img: PIL 图；mask: PIL（白 = 要去掉的地方）。返回 (结果图, 用的方法)。"""
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    rgb = img.convert("RGB")
    mask = mask.convert("L").resize(rgb.size, Image.NEAREST)
    mask = mask.filter(ImageFilter.MaxFilter(5))          # 稍微扩大一圈，水印边缘不留残影
    box = _mask_bbox(mask, pad=max(24, int(max(rgb.size) * 0.04)))
    if not box:
        raise ValueError("先用画笔涂出要去掉的地方")
    st = status()
    use = method if method in ("lama", "opencv", "basic") else st["inpaint"]
    if use == "lama" and not st["lama"]:
        use = "opencv" if st["cv2"] else "basic"
    if use == "opencv" and not st["cv2"]:
        use = "basic"
    crop, mcrop = rgb.crop(box), mask.crop(box)
    fn = {"lama": _inpaint_lama, "opencv": _inpaint_cv2, "basic": _inpaint_basic}[use]
    fixed = fn(crop, mcrop)
    soft = mcrop.filter(ImageFilter.GaussianBlur(2))     # 边缘羽化，接缝看不出来
    out = rgb.copy()
    out.paste(Image.composite(fixed, crop, soft), box[:2])
    if alpha is not None:
        out = out.convert("RGBA")
        out.putalpha(alpha)
    return out, use


# ---------------- 下载 LaMa 模型 ----------------
def install_lama():
    if LAMA_JOB.get("running"):
        return LAMA_JOB

    def run():
        import requests
        LAMA_JOB.clear()
        LAMA_JOB.update(running=True, started=time.time(), done_mb=0)
        tmp = LAMA_PATH + ".part"
        try:
            os.makedirs(LAMA_DIR, exist_ok=True)
            if not _has("onnxruntime"):
                import subprocess
                import sys
                r = subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-q", "onnxruntime"],
                                   capture_output=True, text=True, timeout=1800)
                if r.returncode != 0:
                    raise RuntimeError("安装 onnxruntime 失败：" + (r.stderr or r.stdout)[-300:])
            with requests.get(LAMA_URL, stream=True, timeout=60) as r:
                r.raise_for_status()
                LAMA_JOB["total_mb"] = round(int(r.headers.get("content-length") or 0) / 1e6, 1)
                n = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        n += len(chunk)
                        LAMA_JOB["done_mb"] = round(n / 1e6, 1)
            if n < 50_000_000:
                raise RuntimeError(f"下载的文件太小（{n} 字节），可能被网络拦截了")
            os.replace(tmp, LAMA_PATH)
            LAMA_JOB["ok"] = True
        except Exception as e:  # noqa: BLE001
            LAMA_JOB["error"] = str(e)[:300]
            try:
                os.remove(tmp)
            except OSError:
                pass
        finally:
            LAMA_JOB["running"] = False
    threading.Thread(target=run, daemon=True, name="install-lama").start()
    return {"running": True}
