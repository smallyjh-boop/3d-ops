"""店铺对接（自动导入订单）。

每个平台一个「连接器」：拿到平台开放接口的授权后，定时把新订单/状态变化拉回来，
转换成标准订单格式，交给 orders.upsert（和表格导入、API 推送走同一条路）。

新增一个平台：写一个类继承 Connector，填 PLATFORM / LABEL / FIELDS，实现 fetch_orders()，
在下面 REGISTRY 里登记即可，界面会自动出现。
"""


class NotReady(Exception):
    """连接器还没接通（缺授权信息或还没实现）。"""


class Connector:
    PLATFORM = ""
    LABEL = ""
    READY = False          # 是否已经实现拉取订单
    NOTE = ""              # 界面上的说明
    # 需要填写的授权信息：(键, 显示名, 是否保密)
    FIELDS = []
    OPTIONAL = ()          # FIELDS 里可以不填的键（v2.41.2）
    # v2.49 设置页的店铺表单怎么分组（只影响界面）：一个应用一张卡片，字段按键名前缀归组
    #   [{"slot": 授权时传的 app（主应用 ""）, "prefix": 键名前缀, "title", "for": 用途, "help": 「?」说明, "more": 收进「其他单独应用」}]
    # 不写就是一张「应用授权」卡片；COMMON_FIELDS 放在店铺基本信息那一行（例如回调地址）
    FORM_GROUPS = []
    COMMON_FIELDS = ()
    # v2.34 取平台面单（modules/orders/waybill）：接通后改 True，实现 fetch_label()
    LABEL_READY = False
    LABEL_NOTE = ""
    LABEL_NOTE_TH = ""

    def __init__(self, creds):
        self.creds = dict(creds or {})
        self.creds_changed = False     # 刷新了 token 等需要保存回数据库

    def check(self):
        missing = [label for k, label, _s in self.FIELDS
                   if k not in self.OPTIONAL and not str(self.creds.get(k) or "").strip()]
        if missing:
            raise NotReady("缺少：" + "、".join(missing))

    def fetch_orders(self, since, until):
        """返回 since~until（Unix 秒）之间新建或有变化的订单，标准格式：
        [{platform, shop, order_no, status, order_time, ship_by, buyer, buyer_note, order_total, shipping_fee,
          platform_fee, tracking_no, items:[{sku, name, variation, qty, unit_price, item_total}], raw}]"""
        raise NotReady(f"{self.LABEL} 自动导入还没接通")

    def handle_webhook(self, headers, body, url=""):
        """平台主动推送（webhook）。返回标准订单列表；不支持就返回 None（只记录日志）。"""
        return None

    def fetch_label(self, order):
        """取这个订单的平台面单。返回 {"kind": "pdf" | "png", "data": 文件内容, "tracking_no": "运单号（有就给）"}。
        order 是系统里的订单（order_no、tracking_no、raw 里有平台自己的编号）。"""
        raise NotReady(f"{self.LABEL} 取面单还没接通")


from .lazada import LazadaConnector      # noqa: E402
from .shopee import ShopeeConnector      # noqa: E402
from .others import TikTokConnector, BigSellerConnector   # noqa: E402

REGISTRY = {c.PLATFORM: c for c in (LazadaConnector, ShopeeConnector, TikTokConnector, BigSellerConnector)}


TOKEN_KEYS = ("access_token", "refresh_token")     # 授权后自动得到的，表单里收进「高级（手动填 token）」


def form_groups(c):
    """界面分组（v2.49）：每个字段属于哪一组 —— 键名前缀最长的那组；COMMON_FIELDS 属于 "common"。"""
    groups = [dict(g) for g in (c.FORM_GROUPS or [{"slot": "", "prefix": "", "title": "应用授权"}])]
    by_len = sorted(groups, key=lambda g: -len(g.get("prefix") or ""))

    def group_of(k):
        if k in c.COMMON_FIELDS:
            return "common"
        return next(g["slot"] for g in by_len if k.startswith(g.get("prefix") or ""))
    return groups, group_of


def describe():
    out = []
    for c in REGISTRY.values():
        groups, group_of = form_groups(c)
        fields = []
        for k, label, sec in c.FIELDS:
            g = group_of(k)
            pre = next((x.get("prefix") or "" for x in groups if x["slot"] == g), "")
            fields.append({"key": k, "label": label, "secret": sec, "group": g, "base": k[len(pre):],
                           "token": k[len(pre):] in TOKEN_KEYS, "optional": k in c.OPTIONAL})
        out.append({"platform": c.PLATFORM, "label": c.LABEL, "ready": c.READY, "note": c.NOTE,
                    "fields": fields, "groups": groups})
    return out


def make(platform, creds):
    cls = REGISTRY.get(platform)
    if not cls:
        raise NotReady(f"不支持的平台：{platform}")
    return cls(creds)
