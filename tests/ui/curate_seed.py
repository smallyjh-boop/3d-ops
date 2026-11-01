"""界面测试用：给选品模块塞几条数据（候选、采用过的产品草稿带图片 / 模型文件 / 规格、关注巡逻、采集队列），不连外网。
i18n_server.py 和截图脚本都用它：seed()。"""
import io
import json
import os
import struct
import time


def _cube(s):
    v = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0), (0, 0, s), (s, 0, s), (s, s, s), (0, s, s)]
    t = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    b = io.BytesIO()
    b.write(b"\0" * 80 + struct.pack("<I", len(t)))
    for a, bb, c in t:
        b.write(struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *v[i]) for i in (a, bb, c)) + b"\0\0")
    b.seek(0)
    return b


def seed():
    from PIL import Image, ImageDraw
    from modules.curate import adopt, cand, db, pipeline, watch
    colors = [(96, 165, 250), (52, 211, 153), (251, 191, 36), (244, 114, 182), (167, 139, 250)]

    def fake_img(url, referer=""):
        i = sum(map(ord, url)) % len(colors)
        im = Image.new("RGB", (900, 900), (245, 247, 250))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((180, 260, 720, 700), 60, fill=colors[i])
        d.ellipse((330, 120, 570, 360), fill=colors[(i + 2) % len(colors)])
        b = io.BytesIO()
        im.save(b, "JPEG")
        return b.getvalue()
    adopt.fetch_image = fake_img
    cards = [
        ("https://makerworld.com/en/models/101-honda-click-cup-holder", "Honda Click 125 cup holder", {"downloads": "3.2k", "likes": "410", "makes": "120"}),
        ("https://makerworld.com/en/models/102-cable-clip", "Desk cable clip organizer (no screws)", {"downloads": "1.1k", "likes": "180"}),
        ("https://www.printables.com/model/203-cat-feeder", "Slow feeder bowl insert for cats", {"likes": "95"}),
        ("https://www.printables.com/model/204-pikachu-planter", "Pikachu planter", {"likes": "900"}),
        ("https://www.thingiverse.com/thing:305", "Succulent planter with drip tray", {"n1": "75"}),
        ("https://www.thingiverse.com/thing:306", "Katana display sword", {"n1": "40"}),
    ]
    cand.upsert([{"url": u, "title": t, "metrics": m, "thumb": ""} for u, t, m in cards], "seed")
    # v2.50.1：旧扩展在 Printables 列表页读成了作者名 + 头像 →「采集可能出错」
    cand.upsert([{"url": "https://www.printables.com/model/207-cat-tree", "title": "Fluffy Tails", "author": "Fluffy Tails",
                  "thumb": "https://media.printables.com/media/users/avatars/1/a.jpg"},
                 {"url": "https://www.printables.com/model/208-bowl", "title": "GentleDesign", "thumb": "https://media.printables.com/media/users/avatars/2/b.png"}], "seed")
    c = db.conn()
    c.execute("UPDATE cur_candidates SET ai=?, ai_at=?, new_at=? WHERE skey IN ('mw:101','pr:203','mw:102')",
              (json.dumps({"category": "车和摩托配件", "demand": 85, "est_minutes": 70, "est_grams": 24, "single_color": True, "price_low": 129,
                           "price_high": 199, "competition": "low", "listing": 70, "reason": "泰国摩托车多，杯架刚需", "thai_keywords": ["ที่วางแก้ว"]},
                          ensure_ascii=False), time.time(), time.time()))
    c.commit()
    cand.rescore_all()
    r = adopt.adopt([{"url": cards[1][0]}, {"url": cards[2][0]}], "seed")
    pid = r["added"][0]["product_code"]
    adopt.enrich(pid, {"title": cards[1][1], "author": "Studio Lin", "description_original": "Simple cable clip that slides onto the desk edge. No screws needed.",
                       "tags": "cable, desk, organizer", "license_name": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
                       "image_urls": ["https://makerworld.bblmw.com/a.jpg", "https://makerworld.bblmw.com/b.jpg"],
                       "model_files": [{"name": "clip_small.stl", "url": "https://makerworld.com/f/1"}, {"name": "clip_large.stl", "url": "https://makerworld.com/f/2"},
                                       {"name": "clip_v1_old.zip", "url": "https://makerworld.com/f/3", "size": "900 MB"}]}, "seed")
    c.execute("UPDATE cur_collect SET state='done' WHERE product_id=?", (pid,))
    c.commit()
    for f, s in zip(c.execute("SELECT id, name FROM cur_files WHERE product_id=? AND state='queued' ORDER BY id", (pid,)).fetchall(), (18, 30)):
        watch.file_uploaded(f["id"], f["name"], _cube(s))
    pipeline.run_all()
    for f in ({"kind": "keyword", "site": "pr", "value": "cable organizer"}, {"kind": "url", "value": "https://makerworld.com/en/@studio_lin/upload"}):
        try:
            watch.add(f, "seed")
        except ValueError:
            pass
    w = c.execute("SELECT id FROM cur_watches ORDER BY id LIMIT 1").fetchone()
    if w:
        watch.watch_result(w["id"], [{"url": u, "title": t} for u, t, _m in cards[2:5]])
    return pid
