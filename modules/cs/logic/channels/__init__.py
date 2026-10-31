"""客服的消息渠道（v2.46）。每个渠道一个适配器，客服的其它部分只认这里的统一接口：

  poll(shop)            拉这个店铺的新消息，写进 cs_conv / cs_msg，返回 [会话 id]（有新买家消息的）
  send(conv, msg)       发一条消息到平台：msg = {kind: text/image/item/order, text, extra}，返回平台消息编号
  mark_read(conv)       平台上标记已读

现在有：
  lazada_im   Lazada 开放平台聊天接口（店铺接了接口、开通了 IM 权限）
  extension   浏览器扩展（Shopee 还没接口、店铺数超过接口限制时用；消息由扩展推上来，发送由扩展在页面里填）
  manual      手工粘贴 / 截图

以后加平台（Shopee / TikTok 接口）：写一个同样接口的适配器，在 REGISTRY 里登记。
"""
from . import lazada_im

REGISTRY = {"lazada_im": lazada_im}


def of(conv):
    """会话对应的能直接发送的渠道模块；扩展 / 手工的返回 None（界面改成「复制 + 已发送」）。"""
    return REGISTRY.get((conv or {}).get("channel") or "")
