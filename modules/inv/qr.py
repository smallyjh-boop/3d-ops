"""二维码（v2.52 货位标签用）：纯 Python，不用装别的库。只做标签需要的：字节模式、纠错等级 M、版本 1–6（最多 106 个字节）。

  matrix(text) → [[True/False…]]（True = 黑）
  svg(text, size_mm=20) → <svg>…</svg>（带 4 格白边）
"""
_EC_M = {  # 版本 → (每块数据码字数, 块数, 每块纠错码字数)，纠错等级 M
    1: (16, 1, 10), 2: (28, 1, 16), 3: (44, 1, 26), 4: (32, 2, 18), 5: (43, 2, 24), 6: (27, 4, 16)}
_ALIGN = {2: 18, 3: 22, 4: 26, 5: 30, 6: 34}


def _gf_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    res = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(len(res)):
            res[j] = _gf_mul(res[j], root)
            if j + 1 < len(res):
                res[j] ^= res[j + 1]
        root = _gf_mul(root, 2)
    return res


def _rs_remainder(data, divisor):
    res = [0] * len(divisor)
    for b in data:
        f = b ^ res.pop(0)
        res.append(0)
        for i, coef in enumerate(divisor):
            res[i] ^= _gf_mul(coef, f)
    return res


def _codewords(data):
    for ver in sorted(_EC_M):
        per, blocks, ec = _EC_M[ver]
        if 4 + 8 + 8 * len(data) <= per * blocks * 8:
            break
    else:
        raise ValueError("二维码内容太长")
    per, blocks, ec = _EC_M[ver]
    cap = per * blocks * 8
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in range(7, -1, -1)]
    for b in data:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, cap - len(bits))
    bits += [0] * (-len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < per * blocks:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    div = _rs_divisor(ec)
    dblocks = [words[i * per:(i + 1) * per] for i in range(blocks)]
    eblocks = [_rs_remainder(b, div) for b in dblocks]
    out = [b[i] for i in range(per) for b in dblocks] + [b[i] for i in range(ec) for b in eblocks]
    return ver, out


def _mask_bit(m, x, y):
    return [(x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0, (x // 3 + y // 2) % 2 == 0,
            x * y % 2 + x * y % 3 == 0, (x * y % 2 + x * y % 3) % 2 == 0, ((x + y) % 2 + x * y % 3) % 2 == 0][m]


def _penalty(mod):
    n, p = len(mod), 0
    lines = mod + [list(col) for col in zip(*mod)]
    for ln in lines:                         # 连续同色 5 个以上
        run, prev = 0, None
        for v in ln:
            run = run + 1 if v == prev else 1
            prev = v
            if run == 5:
                p += 3
            elif run > 5:
                p += 1
        s = "".join("1" if v else "0" for v in ln)   # 像定位图形的 1011101
        p += 40 * (s.count("10111010000") + s.count("00001011101"))
    for y in range(n - 1):                   # 2×2 同色
        for x in range(n - 1):
            if mod[y][x] == mod[y][x + 1] == mod[y + 1][x] == mod[y + 1][x + 1]:
                p += 3
    dark = sum(sum(r) for r in mod)
    p += 10 * (abs(dark * 20 - n * n * 10) // (n * n))
    return p


def matrix(text, mask=None):
    data = str(text or "").encode("utf-8")
    ver, words = _codewords(data)
    n = ver * 4 + 17
    mod = [[False] * n for _ in range(n)]
    fn = [[False] * n for _ in range(n)]

    def put(x, y, v):
        mod[y][x] = bool(v)
        fn[y][x] = True

    for i in range(n):                       # 定时图形
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):      # 定位图形 + 分隔白边
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < n and 0 <= y < n:
                    d = max(abs(dx), abs(dy))
                    put(x, y, d not in (2, 4))
    if ver in _ALIGN:                        # 校正图形（版本 2–6 只有右下一个）
        a = _ALIGN[ver]
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                put(a + dx, a + dy, max(abs(dx), abs(dy)) != 1)
    for i in range(9):                       # 格式信息的位置先占上
        for x, y in ((8, i), (i, 8)):
            if not fn[y][x]:
                put(x, y, False)
    for i in range(8):
        put(n - 1 - i, 8, False)
        put(8, n - 1 - i, False)
    put(8, n - 8, True)                      # 固定黑点
    # 放数据（右下往上，两列一组，蛇形）
    i, right, total = 0, n - 1, len(words) * 8
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(n):
            for j in range(2):
                x = right - j
                y = n - 1 - vert if ((right + 1) & 2) == 0 else vert
                if not fn[y][x] and i < total:
                    mod[y][x] = bool((words[i >> 3] >> (7 - (i & 7))) & 1)
                    i += 1
        right -= 2

    def build(m):
        out = [row[:] for row in mod]
        for y in range(n):
            for x in range(n):
                if not fn[y][x] and _mask_bit(m, x, y):
                    out[y][x] = not out[y][x]
        data_ = (0 << 3) | m                 # 纠错等级 M = 00
        rem = data_
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = ((data_ << 10) | rem) ^ 0x5412
        b = lambda k: bool((bits >> k) & 1)  # noqa: E731
        for k in range(6):
            out[k][8] = b(k)
        out[7][8], out[8][8], out[8][7] = b(6), b(7), b(8)
        for k in range(9, 15):
            out[8][14 - k] = b(k)
        for k in range(8):
            out[8][n - 1 - k] = b(k)
        for k in range(8, 15):
            out[n - 15 + k][8] = b(k)
        out[n - 8][8] = True
        return out

    if mask is not None:
        return build(mask)
    return min((build(m) for m in range(8)), key=_penalty)


def svg(text, size_mm=20):
    mod = matrix(text)
    n, q = len(mod), 4
    path = "".join(f"M{x + q},{y + q}h1v1h-1z" for y, row in enumerate(mod) for x, v in enumerate(row) if v)
    w = n + 2 * q
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {w}" width="{size_mm}mm" height="{size_mm}mm" '
            f'shape-rendering="crispEdges"><rect width="{w}" height="{w}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')
