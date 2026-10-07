"""AI 客服模块（独立模块）。

结构：
  data.py      自己的数据表（会话、消息、知识库、学到的回复、客服设置）
  brain.py     AI：找资料、写回复、识别意图、批发报价、读截图
  service.py   业务流程（界面和浏览器扩展共用）
  api.py       网页接口（/api/cs/... 界面用，/api/v1/cs/... 浏览器扩展用）
  erp_link.py  和 ERP（产品、订单、生产）的唯一连接点

接入方式：
  - 软件里「客服」页面：粘贴消息 / 上传聊天截图
  - 浏览器扩展（extension/ 文件夹）：在 Lazada / Shopee / TikTok 卖家中心的聊天页面直接读取、填入回复
  - 以后平台开放接口批下来：在 connectors 里实现聊天收发，调用 service 即可
"""


def install(app):
    from . import api
    api.install(app)
