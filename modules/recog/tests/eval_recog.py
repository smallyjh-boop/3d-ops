"""拍照找产品的准确率评估（不是单元测试，跑一次几分钟；run_all 不会自动跑它）。

    python modules/recog/tests/eval_recog.py [--n 3] [--model PATH_TO_u2netp.onnx] [--json out.json] [--vary rotate,tilt]

做什么：
  1. 临时数据目录里建一个产品库：程序生成的 19 种形状（方块、圆柱、六棱柱、锥、球、雪人、圆环、花瓶、星星、爱心、齿轮、杯子、
     金字塔、L 支架、钥匙扣、手机支架、塔、测试数据里的猫 STL），每种 1~3 个颜色规格，一共 36 个 SKU。
     故意有很多「同形状不同颜色」（方块 白/黑/红…）和「同颜色不同形状」（白色的有 9 个）。
     参考图走正式的流程（refs.build_all）：3D 模型多角度图 + 一部分有白底产品图；猫用测试数据里浏览器（three.js）画的产品图。
  2. 每个 SKU 每种变化拍 n 张「手机照片」（synth.photo）：转 0~360°、倾斜 / 透视、远近 30~100%、只拍到一部分、
     背景（白纸 / 桌面 / 木纹 / 手拿着 / 杂乱）、明暗、白平衡、模糊、JPEG 压缩、噪点、渲染色和实物色不一样、全部一起（中等强度）。
     另外：测试数据里猫的场景图（木桌 / 蓝底，浏览器画的）当成「生活照」查询。
  3. 第一步（本地比对）的前 1 / 前 3 / 前 8 准确率；「产品对了但颜色错了」的比例；
     第二步 AI 只能用假的：模拟一个「看图正确率 p」的 AI（正确答案在前 8 里时以 p 的概率挑对），给出整体预期。
  4. 把握（confidence）校准：把握 ≥ 设置的线时直接用第一个的比例和那时的正确率；低于线时（要员工从前 3 里点）前 3 里有没有正确答案。
"""
import argparse
import collections

import json
import os
import shutil
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
MULTI = True
VARIES = ["base", "rotate", "tilt", "scale", "crop", "bg", "light", "wb", "blur", "jpeg", "noise", "color", "all"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--model", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--vary", default="")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--ai-p", type=float, default=0.9)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--single", action="store_true", help="照片只算一种特征（不用多假设）")
    a = ap.parse_args()
    global MULTI
    MULTI = not a.single
    T = tempfile.mkdtemp(prefix="recog-eval-")
    D = os.path.join(T, "data")
    os.makedirs(os.path.join(D, "products"))
    os.environ["LH_DATA_DIR"] = D
    if a.model:
        md = os.path.join(D, "models")
        os.makedirs(md)
        shutil.copy(a.model, os.path.join(md, "u2netp.onnx"))
    else:
        os.environ["LH_RECOG_NO_MODEL"] = "1"
    sys.path.insert(0, APP)
    import numpy as np
    from core import db, mesh
    db.conn()
    from modules.recog import descriptor, match, refs
    from modules.recog.tests import synth
    match.init()

    # ---- 产品库
    fix = os.path.join(APP, "tests", "fixtures")
    cat = mesh._load_stl(open(os.path.join(fix, "cat.stl"), "rb").read())
    S = synth.shapes(cat)
    z = zipfile.ZipFile(os.path.join(fix, "base_data.zip"))
    p1 = json.loads(z.read("products/3DP0001.json"))
    cat_refs, cat_scenes = [], []
    for img in p1["images"]:
        fn = img["file"]
        try:
            data = z.read(f"products/3DP0001/out/{fn}")
        except KeyError:
            continue
        if img.get("render") in ("main", "angle"):
            cat_refs.append((fn, data, img.get("color")))
        elif fn.startswith("s_"):
            cat_scenes.append(data)
    with_img = {"cube", "cylinder", "heart", "gear", "cup", "keychain", "vase"}
    pid_of = {}
    for k, (name, cols) in enumerate(synth.CATALOG.items(), 1):
        pid = f"EV{k:04d}"
        pid_of[name] = pid
        synth.make_product(pid, name, S[name], cols, cols[:1] if name in with_img else (), cat_refs if name == "cat" else ())
    t0 = time.time()
    job = refs.build_all()
    st = refs.status()
    print(f"参考图：{st['refs']} 张，{st['skus']} 个 SKU，{st['built']} 个产品，用时 {time.time() - t0:.1f}s；{st['kinds']}；"
          f"抠图模型：{'有' if descriptor.model_file() else '没有'} {job['error']}", flush=True)
    skus = sorted(refs.index()["skus"])
    sku_of = {(name, col): f"{pid_of[name]}-{synth.COLOR_CODE[col]}" for name, cols in synth.CATALOG.items() for col in cols}
    rng = np.random.default_rng(a.seed)
    prep = {k: __import__("modules.recog.render", fromlist=["x"]).prepare(v) for k, v in S.items()}
    thr = match.settings()["threshold"]
    rows = []

    def one(vary, truth, raw):
        t1 = time.time()
        q = descriptor.describe_query(raw) if MULTI else descriptor.describe(raw)
        r = match.rank(q)
        cf = match.confidence(r)
        order = [x[0] for x in r]
        rk = order.index(truth) + 1 if truth in order else 0
        prod_ok = bool(order) and order[0].split("-")[0] == truth.split("-")[0]
        rows.append({"vary": vary, "truth": truth, "rank": rk, "top": order[0] if order else "", "prod_ok": prod_ok,
                     "conf": cf[0] if cf else 0, "ms": (time.time() - t1) * 1000, "top3": order[:3]})

    vs = [v for v in (a.vary.split(",") if a.vary else VARIES) if v]
    for v in vs:
        t1 = time.time()
        for (name, col), truth in sku_of.items():
            for _ in range(a.n):
                one(v, truth, synth.photo(None, synth.PALETTE[col], rng, () if v == "base" else (v,), prepared=prep[name]))
        print(f"  {v}: {time.time() - t1:.0f}s", flush=True)
    for raw in cat_scenes:
        one("scene(fixture)", sku_of[("cat", "白色")], raw)

    # ---- 报告
    def stats(rs):
        n = len(rs)
        if not n:
            return {}
        top1 = sum(r["rank"] == 1 for r in rs) / n
        top3 = sum(0 < r["rank"] <= 3 for r in rs) / n
        top8 = sum(0 < r["rank"] <= 8 for r in rs) / n
        prod = sum(r["prod_ok"] for r in rs) / n
        ai = sum((0 < r["rank"] <= 8) * a.ai_p for r in rs) / n
        auto = [r for r in rs if r["conf"] >= thr]
        ask = [r for r in rs if r["conf"] < thr]
        return {"n": n, "top1": top1, "top3": top3, "top8": top8, "product_top1": prod, "with_ai_sim": ai,
                "auto_share": len(auto) / n, "auto_precision": (sum(r["rank"] == 1 for r in auto) / len(auto)) if auto else None,
                "ask_top3": (sum(0 < r["rank"] <= 3 for r in ask) / len(ask)) if ask else None,
                "ms": sum(r["ms"] for r in rs) / n}
    by = collections.OrderedDict()
    for r in rows:
        by.setdefault(r["vary"], []).append(r)
    res = {k: stats(v) for k, v in by.items()}
    res["OVERALL (synthetic)"] = stats([r for r in rows if r["vary"] != "scene(fixture)"])
    f = lambda x: "—" if x is None else f"{x * 100:.0f}%"  # noqa: E731
    print(f"\n| variation | n | top-1 | top-3 | top-8 | right product (any colour) top-1 | with AI (sim p={a.ai_p}) | auto-accept share (conf≥{thr}) | auto-accept precision | below line: truth in top-3 | ms/photo |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for k, s in res.items():
        if s:
            print(f"| {k} | {s['n']} | {f(s['top1'])} | {f(s['top3'])} | {f(s['top8'])} | {f(s['product_top1'])} | {f(s['with_ai_sim'])} | "
                  f"{f(s['auto_share'])} | {f(s['auto_precision'])} | {f(s['ask_top3'])} | {s['ms']:.0f} |")
    conf = collections.Counter((r["truth"], r["top"]) for r in rows if r["rank"] != 1)
    print("\n最常认错的（正确 → 认成）：")
    for (t, p), n in conf.most_common(12):
        print(f"  {t} → {p}  ×{n}")
    sim = [r for r in rows if r["rank"] != 1 and r["top"].split("-")[0] == r["truth"].split("-")[0]]
    print(f"\n认错里「同一个产品、颜色错了」的：{len(sim)} / {sum(r['rank'] != 1 for r in rows)}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fo:
            json.dump({"results": res, "confusions": [[t, p, n] for (t, p), n in conf.most_common(40)], "refs": st}, fo, ensure_ascii=False, indent=1)
    if not a.keep:
        shutil.rmtree(T, ignore_errors=True)



if __name__ == "__main__":
    main()
