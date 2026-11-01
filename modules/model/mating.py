"""自动组合（v2.53，展示模型用）：按零件的几何形状把零件叠 / 插到一起（盖子盖到盒子上、头插到身体上）。

做法（只用 numpy，不靠 AI）：
- 每个零件试 24 个朝向（6 个面朝下 × 绕竖直轴转 4 次）；
- 用「高度图」表示形状：已经摆好的部分从上往下看每一格的最高点（顶面图），新零件从下往上看每一格的最低点（底面图），
  按格子中心取值（像从正上方 / 正下方打一束光），细小的间隙（盖子和盒口之间 0.2 mm）也分得开；
- 新零件在每个位置（水平方向按格子挪）往下落，碰到就停；算「贴合面积」（贴着的格子）、「插进去多深」（盖子的内沿落进盒口、
  头的插销插进身体的孔）、「在下面零件的范围里」，组合成得分，取最高的；
- 置信度：贴合面积大 + 有插进去的结构 → 高；只是平放在上面 → 中；挨不到 → 低（这时建议再用「AI 按图片组装」，或手动调）。
「沉降」settle：任意姿势（例如 AI 给的初稿）里每个零件往下落到碰到下面的零件 / 地面，AI + 几何结合用。
坐标：Z 朝上，毫米；姿势 = 零件外框中心的位置 + XYZ 欧拉角（度，和 assembly.py / three.js 一样）。
"""
import itertools
import math

import numpy as np

MAX_CELLS = 56            # 高度图最长边多少格
MAX_TRIS = 120_000


# ---------------- 旋转 ----------------
def rot_matrix(rx, ry, rz):
    """XYZ 欧拉角（度）→ 旋转矩阵（three.js Euler 'XYZ'：R = Rx · Ry · Rz）。"""
    a, b, c = (math.radians(float(x or 0)) for x in (rx, ry, rz))
    X = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    Y = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    Z = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    return X @ Y @ Z


def euler_of(R):
    """旋转矩阵 → XYZ 欧拉角（度），rot_matrix 的反函数。"""
    R = np.asarray(R, dtype=np.float64)
    b = math.asin(max(-1.0, min(1.0, R[0, 2])))
    if abs(math.cos(b)) > 1e-6:
        a = math.atan2(-R[1, 2], R[2, 2])
        c = math.atan2(-R[0, 1], R[0, 0])
    else:                                        # 万向锁：c 取 0
        a = math.atan2(R[2, 1], R[1, 1])
        c = 0.0
    out = [math.degrees(x) for x in (a, b, c)]
    return [round(((x + 180) % 360) - 180, 2) + 0.0 for x in out]


def orientations():
    """24 个「正」旋转（立方体的旋转群）：带符号的置换矩阵、行列式 = 1。第一个是不转。"""
    out = [np.eye(3)]
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            m = np.zeros((3, 3))
            for i, j in enumerate(perm):
                m[i, j] = signs[i]
            if round(np.linalg.det(m)) == 1 and not np.allclose(m, np.eye(3)):
                out.append(m)
    return out


ORIENTS = orientations()


def posed(tris, center, pos, rot):
    """零件按姿势摆好的三角面（绕原来的外框中心转，再把中心放到 pos）。"""
    v = np.asarray(tris, dtype=np.float64).reshape(-1, 3)
    m = rot_matrix(*(rot or [0, 0, 0]))
    return ((v - np.asarray(center, dtype=np.float64)) @ m.T + np.asarray(pos, dtype=np.float64)).reshape(-1, 3, 3)


# ---------------- 高度图 ----------------
def _decimate(t):
    t = np.asarray(t, dtype=np.float64)
    if len(t) > MAX_TRIS:
        t = t[:: int(math.ceil(len(t) / MAX_TRIS))]
    return t


def heightmaps(tris, cell, x0, y0, nx, ny):
    """按格子中心取：顶面图（每格最高点，没有 = -inf）和底面图（每格最低点，没有 = +inf）。
    格子 (i, j) 的中心 = (x0 + (i + .5) * cell, y0 + (j + .5) * cell)。"""
    t = np.asarray(tris, dtype=np.float64)
    top = np.full(nx * ny, -np.inf)
    bot = np.full(nx * ny, np.inf)
    if not len(t):
        return top.reshape(nx, ny), bot.reshape(nx, ny)
    # 太大的三角形切成 4 个，直到每个在水平面上不超过 4 格
    for _ in range(12):
        xy = t[:, :, :2]
        span = (xy.max(1) - xy.min(1)).max(1)
        big = span > 4 * cell
        if not big.any():
            break
        b = t[big]
        m01, m12, m20 = (b[:, 0] + b[:, 1]) / 2, (b[:, 1] + b[:, 2]) / 2, (b[:, 2] + b[:, 0]) / 2
        subs = np.concatenate([np.stack([b[:, 0], m01, m20], 1), np.stack([m01, b[:, 1], m12], 1),
                               np.stack([m20, m12, b[:, 2]], 1), np.stack([m01, m12, m20], 1)])
        t = np.concatenate([t[~big], subs])
    A, B, C = t[:, 0], t[:, 1], t[:, 2]
    den = (B[:, 1] - C[:, 1]) * (A[:, 0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (A[:, 1] - C[:, 1])
    ok = np.abs(den) > 1e-12                       # 竖着的面（俯视面积 0）不算
    A, B, C, den = A[ok], B[ok], C[ok], den[ok]
    if not len(A):
        return top.reshape(nx, ny), bot.reshape(nx, ny)
    mnx = np.minimum(np.minimum(A[:, 0], B[:, 0]), C[:, 0])
    mny = np.minimum(np.minimum(A[:, 1], B[:, 1]), C[:, 1])
    i0 = np.floor((mnx - x0) / cell - 0.5).astype(np.int64)
    j0 = np.floor((mny - y0) / cell - 0.5).astype(np.int64)
    K = 6
    ki, kj = np.meshgrid(np.arange(K), np.arange(K), indexing="ij")
    ki, kj = ki.ravel(), kj.ravel()
    zs, idx = [], []
    step = max(1, 2_000_000 // (K * K))
    for s in range(0, len(A), step):
        a, b, c, d = A[s:s + step], B[s:s + step], C[s:s + step], den[s:s + step]
        ii = i0[s:s + step, None] + ki[None]
        jj = j0[s:s + step, None] + kj[None]
        px = x0 + (ii + 0.5) * cell
        py = y0 + (jj + 0.5) * cell
        w1 = ((b[:, None, 1] - c[:, None, 1]) * (px - c[:, None, 0]) + (c[:, None, 0] - b[:, None, 0]) * (py - c[:, None, 1])) / d[:, None]
        w2 = ((c[:, None, 1] - a[:, None, 1]) * (px - c[:, None, 0]) + (a[:, None, 0] - c[:, None, 0]) * (py - c[:, None, 1])) / d[:, None]
        w3 = 1 - w1 - w2
        e = -1e-7
        inside = (w1 >= e) & (w2 >= e) & (w3 >= e) & (ii >= 0) & (jj >= 0) & (ii < nx) & (jj < ny)
        z = w1 * a[:, None, 2] + w2 * b[:, None, 2] + w3 * c[:, None, 2]
        zs.append(z[inside])
        idx.append((ii * ny + jj)[inside])
    z = np.concatenate(zs)
    idx = np.concatenate(idx)
    if len(z):
        o = np.argsort(z, kind="stable")
        top[idx[o]] = z[o]                          # 重复的格子留最后一个 = 最大
        o = o[::-1]
        bot[idx[o]] = z[o]
    return top.reshape(nx, ny), bot.reshape(nx, ny)


# ---------------- 自动组合 ----------------
ROLE = None


def _role(name):
    global ROLE
    if ROLE is None:
        from .printplan import _role as r
        ROLE = r
    return ROLE(name)


def _box(t):
    v = t.reshape(-1, 3)
    return v.min(0), v.max(0)


def auto_assemble(parts):
    """parts = [{"key", "name", "tris"（文件里原来的坐标）}]。
    返回 {"poses": {key: {"pos", "rot"}}, "confidence": 0–1, "steps": [{key, on, contact_mm2, insert_mm, conf, orient}], "base": key}。
    第一块（底座 / 主体 / 最大的）不转、放在地面中间；其他按顺序一块块往上叠，每块选得分最高的朝向和位置。"""
    if not parts:
        return {"poses": {}, "confidence": 0.0, "steps": [], "base": None}
    P = []
    for x in parts:
        t = _decimate(x["tris"])
        mn, mx = _box(t)
        P.append({"key": x["key"], "name": x.get("name") or "", "t": t, "center": (mn + mx) / 2, "size": mx - mn,
                  "vol": float(np.prod(np.maximum(mx - mn, 0.1))), "shape": x.get("shape") or x["key"]})
    P.sort(key=lambda q: (_role(q["name"]) if _role(q["name"]) in (0, 1) else 2, -q["vol"]))
    base = P[0]
    maxdim = max(float(np.max(q["size"])) for q in P)
    bmax = float(max(base["size"][0], base["size"][1]))
    cell = max(0.25, bmax / MAX_CELLS, maxdim / (MAX_CELLS * 1.6))
    others = [float(max(q["size"][0], q["size"][1])) for q in P[1:]] or [0.0]
    m = int(math.ceil((max(others) + 2 * cell) / cell))
    bw, bd = float(base["size"][0]), float(base["size"][1])
    # 格子线对齐底座外框的左下角：和底座一样大的盖子正好能对上格子（细小间隙不会被格子吃掉）
    gx0, gy0 = -bw / 2 - m * cell, -bd / 2 - m * cell
    nx, ny = int(math.ceil(bw / cell)) + 2 * m, int(math.ceil(bd / cell)) + 2 * m
    # 底座：不转，外框中心放在 (0, 0)，底面 z = 0
    bt = base["t"] - np.array([base["center"][0], base["center"][1], base["center"][2] - base["size"][2] / 2])
    top, _bot = heightmaps(bt, cell, gx0, gy0, nx, ny)
    T = np.where(np.isfinite(top), np.maximum(top, 0.0), 0.0)
    poses = {base["key"]: {"pos": [0.0, 0.0, round(float(base["size"][2] / 2), 3)], "rot": [0.0, 0.0, 0.0]}}
    steps, confs = [], []
    cache = {}
    tol = max(0.3, 0.15 * cell)
    for q in P[1:]:
        best = None
        for oi, R in enumerate(ORIENTS):
            ck = (q["shape"], oi)
            if ck not in cache:
                v = (q["t"].reshape(-1, 3) - q["center"]) @ R.T
                mn = v.min(0)
                mx = v.max(0)
                bx, by = int(math.ceil((mx[0] - mn[0]) / cell)) or 1, int(math.ceil((mx[1] - mn[1]) / cell)) or 1
                tt = (v - mn).reshape(-1, 3, 3)
                tp, bm = heightmaps(tt, cell, 0.0, 0.0, bx, by)
                cache[ck] = (bm, tp, mn, mx)
            bm, tp, mn, mx = cache[ck]
            r = _drop(T, bm, cell)
            if r is None:
                continue
            score, i, j, zb, contact, insert, cover = r
            if best is None or score > best[0] + 1e-9:
                best = (score, oi, i, j, zb, contact, insert, cover, mn, mx, tp)
        if best is None:
            continue
        score, oi, i, j, zb, contact, insert, cover, mn, mx, tp = best
        R = ORIENTS[oi]
        size = mx - mn
        lo = np.array([gx0 + i * cell, gy0 + j * cell, zb])
        pos = lo + size / 2
        poses[q["key"]] = {"pos": [round(float(x), 3) for x in pos], "rot": euler_of(R)}
        bx, by = tp.shape
        win = T[i:i + bx, j:j + by]
        T[i:i + bx, j:j + by] = np.maximum(win, np.where(np.isfinite(tp), tp + zb, -np.inf))
        nb = float(np.isfinite(bm_of(cache, q, oi)).sum()) or 1.0
        cfrac = contact / nb
        conf = 0.2 + 0.35 * min(1.0, cfrac / 0.3) + 0.35 * min(1.0, insert / 2.0) + 0.1 * cover
        if contact <= 0:
            conf = 0.05
        conf = round(max(0.0, min(1.0, conf)), 2)
        confs.append(conf)
        steps.append({"key": q["key"], "contact_mm2": round(contact * cell * cell, 1), "insert_mm": round(float(insert), 2),
                      "cover": round(float(cover), 2), "conf": conf, "orient": oi})
    return {"poses": poses, "confidence": round(min(confs), 2) if confs else 1.0, "steps": steps, "base": base["key"],
            "cell": round(cell, 3)}


def bm_of(cache, q, oi):
    return cache[(q["shape"], oi)][0]


def _drop(T, bm, cell, tol=None):
    """新零件（底面图 bm）在顶面图 T 上每个位置往下落：返回最好的 (score, i, j, 落下后底面高度, 贴合格数, 插进去多深, 在下面零件范围里的比例)。"""
    nx, ny = T.shape
    bx, by = bm.shape
    if bx > nx or by > ny:
        return None
    valid = np.isfinite(bm)
    nb = int(valid.sum())
    if not nb:
        return None
    tol = tol or max(0.3, 0.15 * cell)
    occ = T > 0.05
    if not occ.any():
        return None
    oi_, oj_ = np.nonzero(occ)
    # 只试「新零件的中心在下面零件的范围里」的位置
    i_lo, i_hi = max(0, oi_.min() - bx // 2), min(nx - bx, oi_.max() - bx // 2)
    j_lo, j_hi = max(0, oj_.min() - by // 2), min(ny - by, oj_.max() - by // 2)
    if i_hi < i_lo or j_hi < j_lo:
        return None
    from numpy.lib.stride_tricks import sliding_window_view
    W = sliding_window_view(T, (bx, by))[i_lo:i_hi + 1, j_lo:j_hi + 1]          # (si, sj, bx, by)
    B = np.where(valid, bm, np.inf)
    diff = W - B                                                                 # 没有材料的格子 = -inf
    zb = diff.max(axis=(2, 3))                                                   # 落下来碰到时零件最低点的高度
    zb = np.maximum(zb, 0.0)
    near = diff >= (zb[..., None, None] - tol)
    on = W > 0.05
    contact = (near & on).sum(axis=(2, 3)).astype(np.float64)
    Wv = np.where(valid, W, -np.inf)
    under = Wv.max(axis=(2, 3))
    insert = np.maximum(0.0, under - zb)                                          # 零件最低点比下面最高点低多少 = 插进去多深
    cover = (valid & on).sum(axis=(2, 3)) / nb
    si, sj = zb.shape
    ci, cj = (oi_.min() + oi_.max() + 1) / 2, (oj_.min() + oj_.max() + 1) / 2
    ii, jj = np.meshgrid(np.arange(si) + i_lo + bx / 2, np.arange(sj) + j_lo + by / 2, indexing="ij")
    off = np.hypot(ii - ci, jj - cj) / max(1.0, max(bx, by))
    cfrac = contact / nb
    hb = float(np.nanmax(np.where(np.isfinite(bm), bm, np.nan))) if nb else 1.0
    inter = (valid & on).sum(axis=(2, 3))
    iou = inter / np.maximum(1, nb + int(occ.sum()) - inter)        # 新零件的范围和下面零件对得上（盖子和盒子一样大）
    score = cfrac + 0.6 * iou + 0.8 * np.minimum(1.0, insert / max(1.0, 0.12 * max(hb, 1.0) + 1.0)) + 0.3 * cover - 0.15 * off
    score = np.where(contact > 0, score, -1.0)
    k = int(np.argmax(score))
    a, b = np.unravel_index(k, score.shape)
    return (float(score[a, b]), int(a + i_lo), int(b + j_lo), float(zb[a, b]), float(contact[a, b]), float(insert[a, b]), float(cover[a, b]))


def settle(parts, poses):
    """任意姿势（例如 AI 的初稿）：从低到高，每个零件竖直往下落，碰到下面的零件或地面就停（水平位置、角度不变）。
    parts = [{"key", "tris", "center"}]；poses = {key: {"pos", "rot"}}。返回新的 poses。"""
    items = []
    for x in parts:
        q = poses.get(x["key"])
        if not q:
            continue
        t = posed(_decimate(x["tris"]), x["center"], q.get("pos") or x["center"], q.get("rot") or [0, 0, 0])
        mn, mx = _box(t)
        items.append((float(mn[2]), x["key"], t, mn, mx))
    if not items:
        return dict(poses)
    items.sort(key=lambda r: r[0])
    allmn = np.min([r[3] for r in items], axis=0)
    allmx = np.max([r[4] for r in items], axis=0)
    span = float(max(allmx[0] - allmn[0], allmx[1] - allmn[1], 1.0))
    cell = max(0.25, span / (MAX_CELLS * 2))
    nx = int(math.ceil((allmx[0] - allmn[0]) / cell)) + 2
    ny = int(math.ceil((allmx[1] - allmn[1]) / cell)) + 2
    x0, y0 = float(allmn[0] - cell), float(allmn[1] - cell)
    T = np.zeros((nx, ny))
    out = {k: dict(v) for k, v in poses.items()}
    for _z, key, t, mn, mx in items:
        tp, bm = heightmaps(t, cell, x0, y0, nx, ny)
        valid = np.isfinite(bm)
        if not valid.any():
            continue
        rel = np.where(valid, bm - mn[2], np.inf)
        zb = max(0.0, float((T - rel)[valid].max()))
        dz = zb - float(mn[2])
        p = list(out[key].get("pos") or [0, 0, 0])
        p[2] = round(float(p[2]) + dz, 3)
        out[key]["pos"] = p
        T = np.maximum(T, np.where(np.isfinite(tp), tp + dz, 0.0))
    return out


# ---------------- 爆炸图 ----------------
def explode(parts, poses, factor=1.0):
    """爆炸图：零件沿组装方向（零件中心分布最开的方向，一般是竖直）拉开。返回 {key: [dx, dy, dz]}（加到 pos 上）。
    parts = [{"key", "tris", "center"}]。"""
    rows = []
    for x in parts:
        q = poses.get(x["key"])
        if not q:
            continue
        t = posed(_decimate(x["tris"])[:: max(1, len(x["tris"]) // 4000)], x["center"], q.get("pos") or x["center"], q.get("rot") or [0, 0, 0])
        mn, mx = _box(t)
        rows.append((x["key"], (mn + mx) / 2, mx - mn))
    if len(rows) < 2:
        return {r[0]: [0.0, 0.0, 0.0] for r in rows}
    C = np.array([r[1] for r in rows])
    S = np.array([r[2] for r in rows])
    mean = C.mean(0)
    d = C - mean
    cov = d.T @ d
    if np.trace(cov) < 1e-6:
        axis = np.array([0.0, 0.0, 1.0])
    else:
        w, V = np.linalg.eigh(cov)
        axis = V[:, int(np.argmax(w))]
        if axis[np.argmax(np.abs(axis))] < 0:
            axis = -axis
        # 竖直方向分布也不小时优先竖直（叠起来的产品最常见）
        if (d[:, 2] ** 2).sum() > 0.35 * w.max():
            axis = np.array([0.0, 0.0, 1.0])
    proj = d @ axis
    order = np.argsort(proj, kind="stable")
    ext = float(np.mean(np.abs(S @ axis))) or 10.0
    gap = (ext * 0.6 + 5.0) * float(factor)
    out = {}
    n = len(rows)
    for rank, k in enumerate(order):
        key = rows[k][0]
        along = (rank - (n - 1) / 2) * gap
        side = d[k] - proj[k] * axis                                            # 横向也稍微拉开一点
        v = axis * along + side * 0.35 * float(factor)
        out[key] = [round(float(x), 2) for x in v]
    return out
