"""电商财务（v2.21）—— 独立模块。别的模块只用这里列出的接口，不要直接读写 fin_* 表。

  收支    expense_categories()  expenses(start, end, category, direction)  save_expense(dict, user)  delete_expense(id, user)
          set_receipt(id, file_storage)  receipt_path(id)
  结算    settle_preview(file_storage)  settle_import(token, mapping, platform, shop, user)  settle_batches()  delete_batch(id, user)
          settle_import_lines(platform, shop, lines, filename, user)   接口拉到的结算明细（按 uid 去重）
          reconcile(start, end)                      对账：已回款 / 金额对不上 / 超时未回款 / 表格里有但系统里没有的订单
  报表    pl(start, end)        损益表（按下单日期，权责发生制）
          breakdown(start, end, by)  by = platform / shop / product / sku / day / month
          cashflow(start, end)  现金流（按钱实际进出的日期：平台回款、其他收入、采购付款、支出）
          tax(start, end)       VAT（设置里开了才算）+ 平台代扣税
          overview(month)       财务总览（本月 vs 上月）
  期间    period(month=None, start=None, end=None) → (起, 止, 说明)

设置（设置 → 财务）：fin_vat_on（默认关）、fin_vat_rate、fin_prices_incl_vat、fin_settle_days、fin_settle_tolerance、fin_fixed_cats。
"""
from . import book as _book
from . import reports as _rep
from . import settle as _settle
from .common import period  # noqa: F401


def init():
    _book.init()
    _settle.init()


expense_categories = _book.categories
expenses = _book.list_expenses
save_expense = _book.save_expense
delete_expense = _book.delete_expense
set_receipt = _book.set_receipt
receipt_path = _book.receipt_path
settle_preview = _settle.preview
settle_import = _settle.do_import
settle_import_lines = _settle.import_lines     # v2.46：接口拉到的结算明细（运营分析模块的 Lazada 财务流水）
settle_batches = _settle.batches
delete_batch = _settle.delete_batch
reconcile = _settle.reconcile
pl = _rep.pl
breakdown = _rep.breakdown
cashflow = _rep.cashflow
tax = _rep.tax
overview = _rep.overview
