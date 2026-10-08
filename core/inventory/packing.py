"""发货包材规则（v2.18 起）：设置 → 库存与采购 →「发货出库：另外每单 / 每件要扣的包材」：
[{item_id, qty, per: "order" 每单 / "item" 每件}]。

v2.35 起由库存模块的「订单发货出库」（modules/inv/shipout.py）按这些规则扣，和成品、纸箱记在同一张出库单里。
inv_order_pack 是 v2.18～v2.34 自动扣过包材的订单（发货出库时不再重复扣包材）。
"""
from .. import db
from ..config import load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_order_pack (order_id INTEGER PRIMARY KEY, doc_id INTEGER, ts REAL);
"""


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


def rules(cfg=None):
    cfg = cfg or load_config()
    out = []
    for r in cfg.get("inv_pack_rules") or []:
        try:
            out.append({"item_id": int(r["item_id"]), "qty": float(r.get("qty") or 1), "per": "item" if r.get("per") == "item" else "order"})
        except (KeyError, TypeError, ValueError):
            continue
    return out
