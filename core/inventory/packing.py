"""发货自动扣包材（v2.18）：订单变成「已发货」时，按设置里的规则开一张领用单（流水类型「发货包材」）。

规则（设置 → 库存与采购 → 发货自动扣包材）：[{item_id, qty, per: "order" 每单 / "item" 每件}]。
每个订单只扣一次（inv_order_pack 记着）；库存不够也照扣（变负数会提醒补货），不影响发货。
只对「在系统里从待发货变成已发货」的订单扣；导入时已经是已发货的历史订单不扣。
"""
import logging

from .. import db
from ..config import load_config
from . import docs, ledger

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_order_pack (order_id INTEGER PRIMARY KEY, doc_id INTEGER, ts REAL);
"""
log = logging.getLogger("3dops")


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


def pack_order(order_id, user=""):
    """返回生成的单据，或 None（没开、没规则、已经扣过）。出错只记日志。"""
    try:
        cfg = load_config()
        if not cfg.get("inv_pack_auto"):
            return None
        rs = rules(cfg)
        if not rs:
            return None
        c = db.conn()
        if c.execute("SELECT 1 FROM inv_order_pack WHERE order_id=?", (order_id,)).fetchone():
            return None
        o = c.execute("SELECT id, order_no, platform FROM orders WHERE id=?", (order_id,)).fetchone()
        if not o:
            return None
        n_items = c.execute("SELECT COALESCE(SUM(qty),0) FROM order_items WHERE order_id=?", (order_id,)).fetchone()[0] or 0
        lines = []
        for r in rs:
            it = ledger.get_item(r["item_id"])
            if not it or not it["active"]:
                continue
            q = r["qty"] * (n_items if r["per"] == "item" else 1)
            if q > 0:
                lines.append({"item_id": it["id"], "qty": q})
        if not lines:
            return None
        c.execute("INSERT INTO inv_order_pack(order_id, ts) VALUES(?,?)", (order_id, ledger._now()))
        c.commit()
        d = docs.create("issue", lines, f"发货包材 订单 {o['order_no']}", user or "系统", ref=f"order:{order_id}",
                        move_kind="pack", allow_negative=True)
        c.execute("UPDATE inv_order_pack SET doc_id=? WHERE order_id=?", (d["id"], order_id))
        c.commit()
        return d
    except Exception as e:  # noqa: BLE001  扣包材失败不能影响发货
        log.warning("发货自动扣包材失败（订单 %s）：%s", order_id, e)
        return None
