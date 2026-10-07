"""还没接通的平台：先把位置留好（授权信息可以先填，接通后直接用）。"""
from . import Connector


class TikTokConnector(Connector):
    PLATFORM = "tiktok"
    LABEL = "TikTok Shop"
    READY = False
    NOTE = "需要在 TikTok Shop Partner Center 申请开发者应用并授权店铺。拿到 App Key 后联系开发者接通。" \
           "接通前可以用 BigSeller 导出表格导入，或通过 API 推送。"
    FIELDS = [("app_key", "App Key", False), ("app_secret", "App Secret", True),
              ("access_token", "Access Token", True), ("refresh_token", "Refresh Token", True),
              ("shop_cipher", "Shop Cipher", False)]


class BigSellerConnector(Connector):
    PLATFORM = "bigseller"
    LABEL = "BigSeller（ERP）"
    READY = False
    NOTE = "BigSeller 目前没有公开的订单接口。可以：① 在 BigSeller 导出订单表格后在订单页导入；" \
           "② 用 BigSeller 的定时导出 / 第三方自动化工具把订单推送到本系统的 API（POST /api/v1/orders）。"
    FIELDS = []
