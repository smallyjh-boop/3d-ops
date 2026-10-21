"""订单发货出库（v2.35）：订单从「待发货」变成「已发货」时，开一张「订单出库」单，一张单写清楚这单扣了什么。

  成品     生产模块开着：这单的生产任务里「用库存发」的个数（下单时先占住，现在才扣）；现打现发的不经过库存，不扣
           生产模块关着：订单里的商品都按成品库存扣（不打印的卖法）
  纸箱     这单用的纸箱（订单模块 packbox：产品设的邮政标准纸箱里最大的一个，打包时可以改；不用纸箱就不扣）
  包材     设置里「另外每单 / 每件要扣的包材」（胶带、气泡袋、感谢卡……）
库存不够也照扣（变负数会提醒补货），不影响发货。每个订单只出库一次（inv_order_out 记着）；
订单又改回「待发货」时，这张单作废（数量冲回），再发货时重新出库。
v2.18 的「发货自动扣包材」（inv_order_pack）扣过的订单，这里不再重复扣包材。
对外：ship_order(oid, user)  revert(oid, user)  summary(oid)
"""
import importlib
import logging
import time

from core import db
from core.config import load_config
from core.inventory import boxes, ledger, packing

docs = importlib.import_module("core.inventory.docs")    # core.inventory.docs 这个名字在包里被 docs() 函数占了，要这样拿模块

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_order_out (order_id INTEGER PRIMARY KEY, doc_id INTEGER, ts REAL);
"""
log = logging.getLogger("3dops")


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


def _goods_lines(c, order):
    from core import chain
    from core.inventory import goods
    out = []
    if chain.prod_on():
        for j in c.execute("SELECT sku, product_id, name, color, COALESCE(stock_n,0) n FROM jobs WHERE order_id=? AND kind='order' "
                           "AND COALESCE(stock_n,0)>0", (order["id"],)):
            out.append((j["sku"], j["product_id"], j["name"], j["color"], int(j["n"])))
    else:
        for it in order.get("items") or []:
            if it.get("sku") and (it.get("qty") or 0) > 0:
                out.append((it["sku"], it.get("product_id"), it.get("name") or "", it.get("color") or "", int(it.get("qty") or 1)))
    lines = []
    for sku, pid, name, color, n in out:
        iid = goods.ensure_item(c, sku, pid, name or "", color or "")
        lines.append({"item_id": iid, "qty": n, "move_kind": "ship", "note": "成品"})
    c.commit()
    return lines


def _box_line(order):
    from core import modules
    pb = modules.public("orders")
    if pb is None or not hasattr(pb, "box_for"):
        return []
    b = pb.box_for(order)
    if not b["code"] or b["code"] == boxes.NONE:
        return []
    iid = boxes.ensure_item(b["code"])
    return [{"item_id": iid, "qty": 1, "move_kind": "pack", "note": "纸箱"}] if iid else []


def _rule_lines(c, order):
    if c.execute("SELECT 1 FROM inv_order_pack WHERE order_id=?", (order["id"],)).fetchone():
        return []                                # v2.18 的自动扣包材已经扣过
    n_items = sum(int(it.get("qty") or 1) for it in order.get("items") or [])
    lines = []
    for r in packing.rules():
        it = ledger.get_item(r["item_id"])
        if not it or not it["active"]:
            continue
        q = r["qty"] * (n_items if r["per"] == "item" else 1)
        if q > 0:
            lines.append({"item_id": it["id"], "qty": q, "move_kind": "pack", "note": "包材"})
    return lines


def ship_order(oid, user=""):
    """订单发货：开出库单。返回单据，或 None（没开、已经出过库、什么都不用扣）。出错只记日志，不影响发货。"""
    try:
        if not load_config().get("inv_ship_out", True):
            return None
        c = db.conn()
        if c.execute("SELECT 1 FROM inv_order_out WHERE order_id=?", (oid,)).fetchone():
            return None
        from core import orders
        o = orders.get_order(oid)
        if not o:
            return None
        lines = _goods_lines(c, o) + _box_line(o) + _rule_lines(c, o)
        # 同一个物品合成一行（例如规则里也写了纸箱）
        merged = {}
        for ln in lines:
            k = (ln["item_id"], ln["move_kind"])
            if k in merged:
                merged[k]["qty"] += ln["qty"]
            else:
                merged[k] = dict(ln)
        # v2.40：停用了的物品（例如停用的纸箱）跳过并记一笔，其它照常出库（以前整张出库单不开，包材也不扣，还不提示）
        skipped = []
        for k in list(merged):
            it = ledger.get_item(merged[k]["item_id"])
            if not it or not it["active"]:
                skipped.append((it or {}).get("name_zh") or str(merged[k]["item_id"]))
                del merged[k]
        if skipped:
            orders.log(oid, user or "系统", "发货出库跳过", "这些物品已停用，没扣库存：" + "、".join(skipped))
        c.execute("INSERT INTO inv_order_out(order_id, ts) VALUES(?,?)", (oid, time.time()))      # 先占住，防止同时出两次库
        c.commit()
        if not merged:
            return None
        try:
            d = docs.create("ship", list(merged.values()), f"订单 {o['order_no']}", user or "系统", ref=f"order:{oid}", allow_negative=True)
        except Exception:
            c.execute("DELETE FROM inv_order_out WHERE order_id=? AND doc_id IS NULL", (oid,))     # v2.40：没开成 → 以后还能再出库
            c.commit()
            raise
        c.execute("UPDATE inv_order_out SET doc_id=? WHERE order_id=?", (d["id"], oid))
        c.commit()
        orders.log(oid, user or "系统", "发货出库", f"{d['no']}：{len(merged)} 样")
        return d
    except Exception as e:  # noqa: BLE001  出库失败不能影响发货
        log.warning("订单发货出库失败（订单 %s）：%s", oid, e)
        return None


def revert(oid, user=""):
    """订单从「已发货」改回「待发货」：出库单作废（数量冲回），以后再发货时重新出库。"""
    try:
        c = db.conn()
        r = c.execute("SELECT doc_id FROM inv_order_out WHERE order_id=?", (oid,)).fetchone()
        if not r:
            return None
        d = None
        if r["doc_id"]:
            cur = docs.get(r["doc_id"])
            if cur and cur["status"] == "done":
                d = docs.void(r["doc_id"], user or "系统")
        c.execute("DELETE FROM inv_order_out WHERE order_id=?", (oid,))
        c.commit()
        from core import orders
        orders.log(oid, user or "系统", "出库单作废", (d or {}).get("no", ""))
        return d
    except Exception as e:  # noqa: BLE001
        log.warning("订单出库单作废失败（订单 %s）：%s", oid, e)
        return None


def summary(oid):
    """订单详情里显示：出库单号、时间、每一行（成品 / 纸箱 / 包材、数量、货位）。没出过库返回 None。"""
    c = db.conn()
    r = c.execute("SELECT doc_id, ts FROM inv_order_out WHERE order_id=?", (oid,)).fetchone()
    if not r or not r["doc_id"]:
        return None
    d = docs.get(r["doc_id"])
    if not d:
        return None
    return {"doc_id": d["id"], "no": d["no"], "status": d["status"], "ts": d["created_at"],
            "lines": [{"code": ln["code"], "name_zh": ln["name_zh"], "name_th": ln["name_th"], "qty": -float(ln["qty"] or 0),
                       "unit": ln["unit"], "category": ln["category"], "location": ln.get("location") or "",
                       "note": ln.get("note") or ""} for ln in d["lines"]]}
