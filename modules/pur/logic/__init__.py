"""采购模块的逻辑（v2.51）。采购单的数据和到货入库在内核 core/inventory/purchase.py；这里是采购模块自己的：
  store       数据表 + 老数据迁移（ensure()）
  links       物品 ↔ 供应商（购买链接、单价、起订量、包装数、到货天数）、价格历史、比价、到货后更新成本
  suggest     补货建议（生产任务 + 近 30 天用量 + 订单量 → 还能用几天、该买多少、红黄绿）→ 按供应商生成采购单
  receiving   到货入库（扫码、差异、放货位、打印标签）
  quick       贴订单文字 / 截图 → AI 读成采购单草稿
  analytics   采购分析（按月 / 分类 / 供应商花了多少、耗材每公斤价格、最便宜的供应商）
  todo        今日待办
"""
from . import analytics, links, quick, receiving, suggest, todo  # noqa: F401
from .store import ensure  # noqa: F401
