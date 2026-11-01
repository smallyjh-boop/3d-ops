"""拍照读文字 / 文字容错的准确率评估（不是单元测试；run_all 不跑）。

    python modules/recog/tests/eval_ocr.py [--n 40]
    （要测真的 OCR：先 pip install rapidocr_onnxruntime，或者 PYTHONPATH 指到装了它的文件夹）

A. 文字容错（模拟 ML Kit / OCR 读错）：系统里真实的货位、SKU、快递单号、订单号，随机加上
   O/0、I/1/l、S/5、B/8、Z/2、G/6 认错 0~3 个字，少横杠，多空格，小写，前后多了别的字（「LOC:」「Tracking No.」）
   → textmatch.match 第一个是不是对的、把握够不够自动用（≥0.8）；另外看「系统里没有的码 / 普通文字」会不会被认错（误认率）。
B. 真的 OCR（装了 rapidocr 才跑）：生成货位牌 / 标签图片（8 种字体、大小、±20° 倾斜、模糊、反光、暗、条码坏了只剩下面的字）
   → ocr.read → 第一个是不是对的。
"""
import argparse
import os
import shutil
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--show", action="store_true", help="列出自动认错的")
    a = ap.parse_args()
    T = tempfile.mkdtemp(prefix="recog-ocr-")
    D = os.path.join(T, "data")
    with zipfile.ZipFile(os.path.join(APP, "tests", "fixtures", "base_data.zip")) as z:
        z.extractall(D)
    os.makedirs(os.path.join(D, "tmp"), exist_ok=True)
    os.environ.update(LH_DATA_DIR=D, LH_NO_MODULE_STARTUP="1", LH_NO_TPL_SYNC="1", LH_NO_PRESETS="1")
    sys.path.insert(0, APP)
    import numpy as np
    import app as A  # noqa: F401  建表
    from core import db, store
    from modules.inv import locations
    from modules.recog import ocr, textmatch
    from modules.recog.tests import synth
    locations.init()
    for zone in "ABC":
        locations.bulk_create(zone, layers=5, positions=6, count=3)
    rng = np.random.default_rng(a.seed)
    c = db.conn()
    orders, tracks = [], []
    for k in range(a.n):
        on = f"{rng.integers(240000, 249999)}{''.join(rng.choice(list('ABCDEFGHJKMNPQRSTUVWXYZ0123456789'), 8))}"
        tn = f"TH{rng.integers(10**9, 10**10 - 1)}{rng.integers(10, 99)}{rng.choice(list('ABCDEFGH'))}"
        c.execute("INSERT INTO orders(platform, order_no, status, tracking_no, order_time) VALUES('lazada',?, 'to_ship', ?, strftime('%s','now'))", (on, tn))
        orders.append(on); tracks.append(tn)
    c.commit()
    textmatch.invalidate()
    locs = [r["code"] for r in locations.locations()]
    skus = [v["sku"] for x in store.list_products() for v in store.load(x["id"]).get("variants") or [] if v.get("sku")]
    truth = {"location": list(rng.choice(locs, min(a.n, len(locs)), replace=False)), "sku": list(rng.choice(skus, min(a.n, len(skus)), replace=False)),
             "tracking": tracks, "order": orders}
    CONF = {"0": "OoDQ", "O": "0", "1": "Il|", "I": "1l", "S": "5", "5": "S", "B": "8", "8": "B", "Z": "2", "2": "Z", "G": "6", "6": "G", "D": "0"}

    def noisy(s, k, drop=False):
        s = list(s)
        idx = [i for i, ch in enumerate(s) if ch in CONF]
        for i in rng.choice(idx, min(k, len(idx)), replace=False) if idx else []:
            s[i] = rng.choice(list(CONF[s[i]]))
        if drop:                                     # 漏读 / 多读一个字（不是易混的字）
            i = int(rng.integers(0, len(s)))
            if rng.random() < 0.5:
                del s[i]
            else:
                s.insert(i, str(rng.choice(list("XK7"))))
        t = "".join(s)
        r = rng.random()
        if r < 0.25:
            t = t.replace("-", "")
        elif r < 0.45:
            t = t.replace("-", " ")
        elif r < 0.55:
            t = t.lower()
        r = rng.random()
        if r < 0.2:
            t = rng.choice(["LOC:", "Tracking No.", "Order:", "SKU", "ตำแหน่ง", "货位"]) + " " + t
        elif r < 0.3:
            t = " ".join(t[i:i + 4] for i in range(0, len(t), 4))
        return t

    print("\nA. 文字容错（模拟 OCR 读错）")
    print("| type | errors/code | n | top-1 | auto-accept (≥0.8) | auto-accept wrong |")
    print("|---|---|---|---|---|---|")
    tot = [0, 0, 0, 0]
    for typ, codes in truth.items():
        for k in (0, 1, 2, 3, "1+drop"):
            n = ok1 = auto = wrong = 0
            for code in codes:
                t = noisy(code, 1, True) if k == "1+drop" else noisy(code, k)
                r = textmatch.match(t)
                n += 1
                good = bool(r) and r[0]["code"] == code
                ok1 += good
                if r and r[0]["conf"] >= 0.8 and r[0]["type"] != "location?":
                    auto += 1
                    wrong += not good
                    if not good and a.show:
                        print(f"    wrong: {code!r} read as {t!r} → {r[:2]}")
            tot = [tot[0] + n, tot[1] + ok1, tot[2] + auto, tot[3] + wrong]
            print(f"| {typ} | {k} | {n} | {ok1 / n * 100:.0f}% | {auto / n * 100:.0f}% | {wrong} |")
    print(f"| ALL | 0-3 | {tot[0]} | {tot[1] / tot[0] * 100:.0f}% | {tot[2] / tot[0] * 100:.0f}% | {tot[3]} |")
    # 误认：系统里没有的码、普通文字
    fake = [f"TH{rng.integers(10**9, 10**10 - 1)}{rng.integers(10, 99)}Z" for _ in range(a.n)] + \
           [f"{rng.integers(250000, 259999)}XYZW{rng.integers(1000, 9999)}" for _ in range(a.n)] + \
           ["Flash Express", "Kerry", "ส่งด่วน", "Bangkok 10110", "COD 299 THB", "Made in Thailand", "PLA+", "Order", "SKU", "3D Ops"]
    fp = sum(1 for t in fake if (lambda r: r and r[0]["conf"] >= 0.8 and r[0]["type"] != "location?")(textmatch.match(t)))
    print(f"\n误认（系统里没有的单号 / 普通文字 {len(fake)} 条，把握 ≥0.8 被认成某个码的）：{fp}")

    engines = ocr.engines()
    print(f"\nB. 真的 OCR：{engines or '没有本地 OCR（跳过）'}")
    if engines:
        conds = {"clean": {}, "angle±20": {"angle": "r"}, "blur": {"blur": 1.8}, "glare": {"glare": True}, "dark": {"dark": True},
                 "small": {"size": 30}, "damaged barcode": {"barcode": True}, "all": {"angle": "r", "blur": 1.2, "glare": True}}
        print("| condition | n | top-1 | text read exactly | ms |")
        print("|---|---|---|---|---|")
        for name, kw in conds.items():
            n = ok1 = exact = 0
            t0 = time.time()
            for i in range(max(8, a.n // 3)):
                typ = ["location", "sku", "tracking", "order"][i % 4]
                code = truth[typ][i % len(truth[typ])]
                k = dict(kw)
                if k.get("angle") == "r":
                    k["angle"] = float(rng.uniform(-20, 20))
                img = synth.text_image(code, rng, font=i, **k)
                r = ocr.read(img, use_ai=False, engine=engines[0])
                n += 1
                ok1 += bool(r["candidates"]) and r["candidates"][0]["code"] == code
                exact += any(textmatch.canon(x) == textmatch.canon(code) for x in r["lines"])
            print(f"| {name} | {n} | {ok1 / n * 100:.0f}% | {exact / n * 100:.0f}% | {(time.time() - t0) / n * 1000:.0f} |")
    shutil.rmtree(T, ignore_errors=True)


if __name__ == "__main__":
    main()
