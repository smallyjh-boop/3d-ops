"""3D 预览用的精简模型（v2.15.2，v2.15.3 改：后台单线程排队预先算好、开机补算、没算好不让浏览器干等）：大模型（几十万面、几十 MB）在浏览器里下载和显示都慢，
预览时先给一个精简版（最多约 20 万面，体积小很多），放大看细节、出商品图时浏览器再去读完整模型。

精简方法：顶点聚类（按小格子合并相近的顶点，去掉退化的三角面）。形状基本不变，只是细节少一些。
结果缓存在 data/cache/preview/，模型文件没变就不重新算。

二进制格式（gzip 压缩传输）：
  "3DPV" | 顶点数 u32 | 三角面数 u32 | 原始面数 u32 | 顶点 float32×3 | 索引 uint32×3 | JSON 长度 u32 | JSON（完整模型的尺寸 / 体积）
"""
import gzip
import hashlib
import json
import os
import queue
import struct
import threading
import time

import numpy as np

from .config import DATA_DIR

CACHE = os.path.join(DATA_DIR, "cache", "preview")
TARGET = 200_000
SYNC_BYTES = 6 * 1024 * 1024      # 小于这个大小的文件，没缓存也当场算（一两秒内）；大文件后台算，浏览器先读完整模型
_locks = {}
_locks_guard = threading.Lock()
_q = queue.Queue()
_queued = set()
_worker = None


def _key(fp, target):
    st = os.stat(fp)
    return hashlib.sha1(f"{os.path.abspath(fp)}|{st.st_mtime}|{st.st_size}|{target}|v2".encode()).hexdigest()[:20]


def _index(tris, cell):
    """顶点按 cell 大小的格子合并（cell=0：按 0.001mm 合并完全相同的顶点）。返回 (verts, idx)。
    用一维整数键做 unique，几百万个顶点也只要零点几秒。"""
    v = tris.reshape(-1, 3).astype(np.float64)
    c = cell if cell > 0 else 0.001
    q = np.floor((v - v.min(0)) / c).astype(np.int64)
    span = q.max(0) + 1
    key = (q[:, 0] * span[1] + q[:, 1]) * span[2] + q[:, 2]
    _u, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    verts = np.zeros((len(cnt), 3))
    for k in range(3):
        verts[:, k] = np.bincount(inv, weights=v[:, k], minlength=len(cnt))
    verts /= cnt[:, None]
    idx = inv.reshape(-1, 3)
    ok = (idx[:, 0] != idx[:, 1]) & (idx[:, 1] != idx[:, 2]) & (idx[:, 0] != idx[:, 2])
    return verts.astype(np.float32), idx[ok].astype(np.uint32)


def simplify(tris, target=TARGET):
    """返回 (verts, idx, reduced)。面数不多的模型只做顶点合并（不丢细节）。"""
    if len(tris) <= target:
        v, i = _index(tris, 0)
        return v, i, False
    # 先按「面数和格子大小的平方大致成反比」估一个格子大小，再微调一两次
    p = tris.reshape(-1, 3)
    diag = float(np.linalg.norm(p.max(0) - p.min(0))) or 1.0
    cell = diag / (np.sqrt(target) * 1.6)
    for _ in range(6):
        v, i = _index(tris, cell)
        if len(i) <= target * 1.1:
            if len(i) < target * 0.5 and _ < 5:      # 合并过头了，格子缩小一点再来
                cell *= max(0.6, np.sqrt(len(i) / target))
                continue
            return v, i, True
        cell *= max(1.1, np.sqrt(len(i) / target))
    return v, i, True


def cache_path(fp, target=TARGET):
    return os.path.join(CACHE, _key(fp, target) + ".bin.gz")


def ready(fp, target=TARGET):
    try:
        return os.path.exists(cache_path(fp, target))
    except OSError:
        return False


def _lock_for(k):
    with _locks_guard:
        if len(_locks) > 200:
            _locks.clear()
        return _locks.setdefault(k, threading.Lock())


def build(fp, metrics_fn, target=TARGET):
    """读模型文件 → 精简 → 打包（gzip 过的字节）。有缓存直接用。同一个文件同时只算一次（另一个等它算完直接读缓存）。"""
    os.makedirs(CACHE, exist_ok=True)
    cp = cache_path(fp, target)
    if os.path.exists(cp):
        with open(cp, "rb") as f:
            return f.read()
    with _lock_for(cp):
        if os.path.exists(cp):
            with open(cp, "rb") as f:
                return f.read()
        t0 = time.time()
        from . import kernels
        data = kernels.preview_bytes(fp, target)       # 大文件交给电脑算（v2.20）
        tmp = cp + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, cp)
        try:
            from . import diag
            diag.note("3D 预览模型已生成：%s（%.1f MB，用时 %.1f 秒）", os.path.basename(fp),
                      os.path.getsize(fp) / 1048576, time.time() - t0)
        except Exception:  # noqa: BLE001
            pass
    _trim()
    return data


def _make(fp, metrics_fn, target):
    from . import modellib
    parts = modellib.load_parts(fp)
    tris = np.concatenate([t for _n, t in parts]).astype(np.float32)
    del parts
    if not len(tris):
        raise ValueError("模型里没有三角面")
    verts, idx, reduced = simplify(tris, target)
    info = json.dumps({"metrics": metrics_fn(tris), "reduced": reduced, "triangles": int(len(tris))}, ensure_ascii=False).encode()
    raw = b"3DPV" + struct.pack("<III", len(verts), len(idx), len(tris)) + verts.tobytes() + idx.tobytes() \
        + struct.pack("<I", len(info)) + info
    return gzip.compress(raw, 5)


def _trim(keep=200):
    """缓存最多留 200 个（按时间删最旧的）。"""
    try:
        fs = sorted((os.path.join(CACHE, n) for n in os.listdir(CACHE)), key=os.path.getmtime)
        for f in fs[:-keep]:
            os.remove(f)
    except OSError:
        pass


def warm(fp):
    """后台提前把预览模型算好（上传 / 换模型 / 开机后调用）。只用一个后台线程排队算（NAS 的 CPU 和内存都有限），出错不管。"""
    global _worker
    if not fp or ready(fp):
        return
    with _locks_guard:
        if fp in _queued:
            return
        _queued.add(fp)
        _q.put(fp)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, daemon=True, name="preview-warm")
            _worker.start()


def _run():
    from . import filemgr
    while True:
        try:
            fp = _q.get(timeout=60)
        except queue.Empty:
            return
        try:
            if os.path.exists(fp):
                build(fp, filemgr.metrics)
        except Exception as e:  # noqa: BLE001
            try:
                from . import diag
                diag.log.warning("3D 预览模型生成失败：%s：%s", os.path.basename(fp), e)
            except Exception:  # noqa: BLE001
                pass
        finally:
            with _locks_guard:
                _queued.discard(fp)


def warm_all(min_bytes=SYNC_BYTES, delay=20):
    """开机后：把所有产品的 3D 模型、模型库里的大文件都排队算好预览（已经算好的跳过）。
    小文件不用（当场算也很快）。等 delay 秒再开始，不跟开机抢 CPU。"""
    def go():
        time.sleep(delay)
        try:
            from . import filemgr, modellib, store
            n = 0
            for item in store.list_products():
                pid = item.get("id") if isinstance(item, dict) else item
                try:
                    p = store.load(pid)
                except Exception:  # noqa: BLE001
                    continue
                fps = [filemgr.model_path(p)] + [modellib.path_of(pid, e) for e in p.get("model_lib") or []]
                for fp in fps:
                    try:
                        if fp and os.path.getsize(fp) >= min_bytes and not ready(fp):
                            warm(fp)
                            n += 1
                    except OSError:
                        pass
            if n:
                from . import diag
                diag.note("开机补算 3D 预览模型：%d 个排队中", n)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=go, daemon=True, name="preview-warm-all").start()
