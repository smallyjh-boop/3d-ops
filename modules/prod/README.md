- 系统 v2.55.0（上线前复审，打印机编码）：单台改编码、设置页保存、批量重新编号走同一套（`fleetcodes.migrate_po_refs` + `fleetcodes.note_code_changes`）；互换 / 复用编码时，旧编码已经是别的打印机当前编码的，不再放 `old_codes`（会悄悄打开错的机器），改记 `stale_codes`，扫到时提示「这个编码已换给别的打印机，请重新打印标签」（`/api/fleet/printers/<key>` 返回 `stale_label`）；批量重新编号的结果带 `relabel`，页面弹出「这些机器要重新打印标签」。新打印的标签二维码装稳定 id（`?printer=<id>`，牌子上大字仍是编码），扫码 id / 编码 / 旧编码都认。测试 tests/t_codes255.py。
- （系统 v2.56.0，T36）机型模板加「编辑用的切片软件」（slicer_app：自动 / Bambu Studio / OrcaSlicer；自动 = 拓竹用 Bambu Studio，其它用 OrcaSlicer；
  设置 → 生产 机型模板表多一列，单台打印机的「单独设置」里也能改；「auto」= 不存）。打印方案「在切片软件里编辑」按这一盘的机型选软件（core/fleet.slicer_app_of）。
