"use strict";
// 手机页（/m）：拿着手机扫码干活。页面：首页方块、查订单、扫码发货交接、验货、库存、盘点、货位。
// 扫码见 scan.js（摄像头一直开着 / 扫码枪 / 手输），每个页面用 SCAN.on(处理函数) 接码。
// 接口尽量用现成的：/api/pack/lookup + /api/pack/done（验货）、/api/handovers（交接）、/api/inv/docs（出入库）、
// /api/inv/stocktake（盘点）、/api/inv/locations/assign（放货位）；新的只有 /api/mobile/…（扫码识别、查订单、照片）。
// 断网：交接扫码、出入库、放货位、验货完成先存在手机里（localStorage），联网后自动补上；补的时候被拒绝的会大声提醒。
// 文字：每句都有中文和泰文（L 表）；后台发来的中文提示用 i18n.js 的 I18N.t 翻成泰文。
(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let LANG = "zh";
  try { LANG = localStorage.getItem("ui_lang") || "zh"; } catch { /* 默认中文 */ }
  const TH = () => LANG === "th";

  // ---------------- 文字（中文 / 泰文） ----------------
  const L = {
    "app": ["3D 运营 · 手机", "3D Ops · มือถือ"],
    "home": ["首页", "หน้าแรก"],
    "t.order": ["查订单", "ค้นหาออเดอร์"], "t.order.s": ["扫面单或输入订单号 / 买家", "สแกนใบปะหน้าหรือพิมพ์เลขออเดอร์ / ชื่อผู้ซื้อ"],
    "t.ship": ["扫码发货交接", "สแกนส่งมอบพัสดุ"], "t.ship.s": ["交给快递：一包一扫", "ส่งให้ขนส่ง: สแกนทีละกล่อง"],
    "t.pack": ["验货", "ตรวจแพ็ก"], "t.pack.s": ["扫面单再扫商品", "สแกนใบปะหน้าแล้วสแกนสินค้า"],
    "t.stock": ["库存", "สต็อก"], "t.stock.s": ["查数量、入库、出库", "ดูจำนวน รับเข้า เบิกออก"],
    "t.count": ["盘点", "ตรวจนับ"], "t.count.s": ["扫货位再扫商品", "สแกนตำแหน่งแล้วสแกนสินค้า"],
    "t.loc": ["货位", "ตำแหน่งจัดเก็บ"], "t.loc.s": ["在哪、放哪、换位置", "อยู่ไหน วางที่ไหน ย้ายที่"],
    "t.rcv": ["采购到货", "รับของจัดซื้อ"], "t.rcv.s": ["扫采购单 / 物品，点数入库", "สแกนใบสั่งซื้อ / สินค้า นับแล้วรับเข้า"],
    "scan.any": ["直接扫任何码：订单、商品、货位都认得", "สแกนได้เลย: ออเดอร์ สินค้า ตำแหน่ง ระบบรู้จักหมด"],
    "ph.scan": ["扫码或输入…", "สแกนหรือพิมพ์…"],
    "logout": ["退出登录", "ออกจากระบบ"],
    "login.t": ["登录", "เข้าสู่ระบบ"], "login.user": ["用户名", "ชื่อผู้ใช้"], "login.pw": ["密码", "รหัสผ่าน"], "login.go": ["登录", "เข้าสู่ระบบ"],
    "full": ["打开完整网页版", "เปิดเวอร์ชันเว็บเต็ม"],
    "cam.insecure": ["浏览器在局域网 http 地址上不能开摄像头。<br>请装「安卓 App」（设置 → 组件与插件），或用扫码枪 / 在下面手动输入。",
      "เบราว์เซอร์เปิดกล้องบนที่อยู่ http ในวง LAN ไม่ได้<br>กรุณาติดตั้ง「แอป Android」(ตั้งค่า → ส่วนประกอบและปลั๊กอิน) หรือใช้เครื่องสแกน / พิมพ์ด้านล่าง"],
    "cam.nodetector": ["这个浏览器不能用摄像头扫码。请装「安卓 App」，或用扫码枪 / 手动输入。", "เบราว์เซอร์นี้สแกนด้วยกล้องไม่ได้ กรุณาติดตั้ง「แอป Android」หรือใช้เครื่องสแกน / พิมพ์เอง"],
    "cam.denied": ["打不开摄像头（没给权限？）。可以用扫码枪 / 手动输入。", "เปิดกล้องไม่ได้ (ไม่ได้อนุญาต?) ใช้เครื่องสแกน / พิมพ์เองได้"],
    "offline.q": ["没网络：已存在手机里，联网后自动补上", "ไม่มีเน็ต: เก็บไว้ในเครื่องแล้ว จะส่งอัตโนมัติเมื่อต่อเน็ต"],
    "q.title": ["没传上去的扫码", "รายการที่ยังส่งไม่ได้"], "q.pending": ["等联网", "รอเน็ต"], "q.failed": ["被拒绝了（要处理）", "ถูกปฏิเสธ (ต้องจัดการ)"],
    "q.retry": ["马上重试", "ลองใหม่ตอนนี้"], "q.clear": ["清掉被拒绝的", "ล้างรายการที่ถูกปฏิเสธ"], "q.sent": ["已补传 {n} 条", "ส่งย้อนหลังแล้ว {n} รายการ"],
    "q.rejected": ["补传被拒绝：{msg}", "ส่งย้อนหลังถูกปฏิเสธ: {msg}"],
    "close": ["关闭", "ปิด"], "cancel": ["取消", "ยกเลิก"], "ok": ["确定", "ตกลง"], "save": ["保存", "บันทึก"], "back": ["返回", "กลับ"],
    "unknown": ["不认识这个码：{c}", "ไม่รู้จักโค้ดนี้: {c}"],
    "net": ["连不上服务器", "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้"],
    "loading": ["加载中…", "กำลังโหลด…"],
    // 订单
    "o.scan": ["扫面单条码，或输入订单号 / 运单号 / 买家名", "สแกนบาร์โค้ดใบปะหน้า หรือพิมพ์เลขออเดอร์ / เลขพัสดุ / ชื่อผู้ซื้อ"],
    "o.found": ["找到 {n} 个订单", "พบ {n} ออเดอร์"], "o.none": ["没找到订单", "ไม่พบออเดอร์"],
    "o.tracking": ["运单", "เลขพัสดุ"], "o.carrier": ["物流", "ขนส่ง"], "o.buyer": ["买家", "ผู้ซื้อ"], "o.receiver": ["收件人", "ผู้รับ"],
    "o.shipby": ["最晚发货", "ส่งภายใน"], "o.time": ["下单", "สั่งซื้อ"], "o.cod": ["货到付款", "เก็บเงินปลายทาง"],
    "o.items": ["商品", "สินค้า"], "o.prod": ["生产进度", "ความคืบหน้าการผลิต"], "o.nojobs": ["没有生产任务（用库存发 / 不用打印）", "ไม่มีงานผลิต (ส่งจากสต็อก / ไม่ต้องพิมพ์)"],
    "o.handover": ["交接单", "ใบส่งมอบ"], "o.photos": ["照片", "รูปถ่าย"], "o.pack": ["✅ 验货这单", "✅ ตรวจแพ็กออเดอร์นี้"],
    "o.photo": ["📷 拍照", "📷 ถ่ายรูป"], "o.custom": ["定制要求", "ความต้องการพิเศษ"], "o.bnote": ["买家留言", "ข้อความผู้ซื้อ"],
    "o.late": ["已超时", "เลยกำหนดแล้ว"], "o.hold": ["待审核挂起", "พักไว้รอตรวจ"], "o.closed": ["已交出", "ส่งมอบแล้ว"], "o.open": ["交接中", "กำลังส่งมอบ"],
    "o.isitem": ["这是商品 / 物品码", "นี่คือโค้ดสินค้า / สิ่งของ"], "o.isloc": ["这是货位码", "นี่คือโค้ดตำแหน่ง"],
    "go.stock": ["打开库存", "เปิดสต็อก"], "go.loc": ["打开货位", "เปิดตำแหน่ง"], "go.order": ["打开订单", "เปิดออเดอร์"],
    // 交接
    "s.pick": ["选物流（快递员是哪家）", "เลือกขนส่ง (พนักงานของบริษัทไหน)"], "s.open": ["没交完的交接单", "ใบส่งมอบที่ยังไม่เสร็จ"],
    "s.continue": ["继续", "ทำต่อ"], "s.toship": ["{n} 单待发货", "รอส่ง {n} ออเดอร์"], "s.other": ["其他物流", "ขนส่งอื่น"],
    "s.start": ["开始扫", "เริ่มสแกน"], "s.any": ["不分物流", "ไม่แยกขนส่ง"], "s.carrier_ph": ["物流名称，例如 Flash", "ชื่อขนส่ง เช่น Flash"],
    "s.scan": ["一包一扫：扫面单上的运单号", "สแกนทีละกล่อง: สแกนเลขพัสดุบนใบปะหน้า"], "s.count": ["已扫", "สแกนแล้ว"],
    "s.close": ["✅ 交接完成（标记已发货）", "✅ ส่งมอบเสร็จ (เปลี่ยนเป็นจัดส่งแล้ว)"], "s.print": ["🖨 交接单", "🖨 ใบส่งมอบ"],
    "s.switch": ["换物流", "เปลี่ยนขนส่ง"], "s.close_q": ["交接完成？{n} 单标记为「已发货」", "ยืนยันส่งมอบ? {n} ออเดอร์จะเปลี่ยนเป็น「จัดส่งแล้ว」"],
    "s.closed": ["交接完成：{n} 单已发货", "ส่งมอบเสร็จ: จัดส่งแล้ว {n} ออเดอร์"], "s.added": ["✔ {no}", "✔ {no}"],
    "s.remove_q": ["把 {no} 移出交接单？", "เอา {no} ออกจากใบส่งมอบ?"], "s.empty": ["还没扫", "ยังไม่ได้สแกน"],
    "s.queued": ["⏳ {c}（等联网）", "⏳ {c} (รอเน็ต)"],
    // 验货
    "p.wait": ["扫面单（订单号 / 快递单号）开始验货", "สแกนใบปะหน้า (เลขออเดอร์ / เลขพัสดุ) เพื่อเริ่มตรวจ"],
    "p.found_scan": ["请扫每件商品的条码", "สแกนบาร์โค้ดสินค้าทีละชิ้น"], "p.found_tap": ["对着图片核对，点「✓」", "ดูรูปแล้วกด「✓」"],
    "p.need": ["要装", "ต้องแพ็ก"], "p.got": ["已核对", "ตรวจแล้ว"], "p.left": ["还差 {n} 件", "ยังขาด {n} ชิ้น"], "p.all": ["全部核对好了", "ตรวจครบแล้ว"],
    "p.scanit": ["扫商品码", "สแกนโค้ดสินค้า"], "p.tap": ["✓ 装好了", "✓ แพ็กแล้ว"], "p.none": ["不用核对", "ไม่ต้องตรวจ"],
    "p.extra": ["{c} 多了！这单只要 {n} 件", "{c} เกิน! ออเดอร์นี้ต้องการแค่ {n} ชิ้น"],
    "p.wrong": ["{c} 不是这个订单的商品！", "{c} ไม่ใช่สินค้าของออเดอร์นี้!"],
    "p.switch": ["换成订单 {no}（上一单还没验完）", "เปลี่ยนเป็นออเดอร์ {no} (ออเดอร์ก่อนยังตรวจไม่เสร็จ)"],
    "p.done": ["✅ 验货完成", "✅ ตรวจแพ็กเสร็จ"], "p.reset": ["换一单", "เปลี่ยนออเดอร์"],
    "p.notship": ["这单是「{st}」，不是待发货，确认一下", "ออเดอร์นี้สถานะ「{st}」 ไม่ใช่รอจัดส่ง ตรวจสอบก่อน"],
    "p.jobs": ["还有 {n} 个生产任务没打完", "ยังมีงานผลิตไม่เสร็จ {n} งาน"],
    "p.ok": ["验货完成 ✔ {n} 个任务标记已打包", "ตรวจแพ็กเสร็จ ✔ งาน {n} งานเป็นแพ็กแล้ว"],
    "p.photo_q": ["拍一张打包照片留证据？", "ถ่ายรูปการแพ็กเก็บไว้เป็นหลักฐาน?"], "p.photo": ["📷 拍打包照片", "📷 ถ่ายรูปการแพ็ก"],
    "p.skip": ["跳过，下一单", "ข้าม ออเดอร์ถัดไป"], "p.photo_ok": ["照片已保存（{n} 张）", "บันทึกรูปแล้ว ({n} รูป)"],
    "p.plus": ["+1（条码坏了）", "+1 (บาร์โค้ดเสีย)"], "p.box": ["纸箱", "กล่อง"],
    // 库存
    "k.scan": ["扫商品 / 物品条码看库存", "สแกนบาร์โค้ดสินค้า / สิ่งของเพื่อดูสต็อก"],
    "k.qty": ["库存", "คงเหลือ"], "k.loc": ["货位", "ตำแหน่ง"], "k.noloc": ["没放货位", "ยังไม่มีตำแหน่ง"], "k.low": ["低于补货线", "ต่ำกว่าจุดสั่งซื้อ"],
    "k.free": ["可用成品（扣掉订单占用）", "สินค้าพร้อมใช้ (หักที่ออเดอร์จองแล้ว)"],
    "k.in": ["入库", "รับเข้า"], "k.out": ["出库", "เบิกออก"], "k.set": ["改成实数", "แก้เป็นจำนวนจริง"],
    "k.r.purchase": ["采购到货", "ซื้อเข้า"], "k.r.return": ["退回入库", "คืนเข้าสต็อก"], "k.r.issue": ["领用", "เบิกใช้"], "k.r.scrap": ["报废", "ทิ้ง/เสียหาย"],
    "k.note": ["备注 / 原因", "หมายเหตุ / เหตุผล"], "k.submit": ["确定", "ยืนยัน"], "k.actual": ["实际数量", "จำนวนจริง"],
    "k.done": ["✔ {name}：{q}", "✔ {name}: {q}"], "k.same": ["数量没变", "จำนวนไม่เปลี่ยน"],
    "k.nofile": ["这个 SKU 还没有库存档", "SKU นี้ยังไม่มีในระบบสต็อก"], "k.create": ["建库存档", "สร้างรายการสต็อก"],
    "k.adjnote": ["手机盘点改数", "แก้จำนวนจากมือถือ"], "k.scrapnote": ["请写报废原因", "กรุณาใส่เหตุผลที่ทิ้ง"],
    "k.noinv": ["库存模块没有打开", "ไม่ได้เปิดโมดูลสต็อก"],
    // 盘点
    "c.scan": ["先扫货位 / 货架条码，开始盘点", "สแกนโค้ดตำแหน่ง / ชั้นวางก่อน เพื่อเริ่มตรวจนับ"],
    "c.area": ["盘点范围", "ขอบเขตตรวจนับ"], "c.book": ["账面", "ในระบบ"], "c.counted": ["实盘", "นับได้"],
    "c.save": ["💾 保存", "💾 บันทึก"], "c.confirm": ["✅ 确认盘点（改库存）", "✅ ยืนยันตรวจนับ (แก้สต็อก)"], "c.zero": ["没扫到的算 0", "ที่ไม่ได้สแกนนับเป็น 0"],
    "c.notin": ["{c} 不在这里的账上{w}", "{c} ไม่อยู่ในรายการที่นี่{w}"], "c.at": ["（账上在 {l}）", " (ในระบบอยู่ที่ {l})"],
    "c.saved": ["已保存", "บันทึกแล้ว"], "c.confirmed": ["盘点完成，{n} 个有差异已调整", "ตรวจนับเสร็จ ปรับ {n} รายการที่ต่าง"],
    "c.confirm_q": ["确认盘点？填了数的按实盘数改库存", "ยืนยันตรวจนับ? รายการที่กรอกจะแก้สต็อกตามจำนวนจริง"],
    "c.new": ["换个货位盘点", "ตรวจตำแหน่งอื่น"], "c.diff": ["差", "ต่าง"], "c.needitem": ["这是商品码：先扫货位开始盘点", "นี่คือโค้ดสินค้า: สแกนตำแหน่งก่อน"],
    // 货位
    "l.scan": ["扫货位看里面有什么；扫商品看它在哪", "สแกนตำแหน่งดูว่ามีอะไร สแกนสินค้าดูว่าอยู่ไหน"],
    "l.empty": ["这个货位是空的", "ตำแหน่งนี้ว่าง"], "l.putin": ["📥 把东西放到这里", "📥 วางของที่นี่"], "l.move": ["↔ 放到 / 换到别的货位", "↔ วาง / ย้ายไปตำแหน่งอื่น"],
    "l.takeoff": ["拿下来（不放货位）", "เอาออก (ไม่มีตำแหน่ง)"],
    "l.mode_put": ["放到 {l}：扫要放进来的商品", "วางที่ {l}: สแกนสินค้าที่จะวาง"], "l.mode_move": ["{name}：扫新的货位", "{name}: สแกนตำแหน่งใหม่"],
    "l.stop": ["结束", "เสร็จ"], "l.put_ok": ["✔ {c} → {l}", "✔ {c} → {l}"], "l.where": ["在", "อยู่ที่"], "l.shelf": ["货架 {c}", "ชั้นวาง {c}"],
    "l.nofile": ["还没有库存档，先在「库存」里入库", "ยังไม่มีในสต็อก ให้รับเข้าที่「สต็อก」ก่อน"],
    "l.takeoff_q": ["把 {c} 从货位拿下来？", "เอา {c} ออกจากตำแหน่ง?"],
    // 采购到货（v2.51）
    "r.scan": ["扫采购单号 / 物流单号 / 物品条码", "สแกนเลขใบสั่งซื้อ / เลขพัสดุ / บาร์โค้ดสินค้า"], "r.transit": ["在途的采购单", "ใบสั่งซื้อที่กำลังส่ง"],
    "r.none": ["没有在途的采购单", "ไม่มีใบสั่งซื้อที่กำลังส่ง"], "r.late": ["晚了 {n} 天", "ช้า {n} วัน"], "r.today": ["今天到", "ถึงวันนี้"],
    "r.days": ["还有 {n} 天", "อีก {n} วัน"], "r.left": ["还没到", "ยังไม่ถึง"], "r.got": ["这次到了", "ถึงรอบนี้"], "r.roll": ["卷", "ม้วน"],
    "r.issue": ["⚠ 有问题（少发 / 破损）", "⚠ มีปัญหา (ขาด / เสีย)"], "r.k.short": ["少发", "ส่งขาด"], "r.k.damaged": ["破损", "เสียหาย"],
    "r.k.wrong": ["发错", "ส่งผิด"], "r.k.extra": ["多发", "ส่งเกิน"], "r.iq": ["数量", "จำนวน"], "r.inote": ["说明", "หมายเหตุ"],
    "r.loc": ["放到货位（可空）", "วางตำแหน่ง (เว้นได้)"], "r.ok": ["✅ 确认入库", "✅ ยืนยันรับเข้า"], "r.done": ["已入库：{no}", "รับเข้าแล้ว: {no}"],
    "r.print": ["🏷 打印物品标签", "🏷 พิมพ์ป้ายสินค้า"], "r.next": ["下一张", "ใบถัดไป"], "r.notopen": ["这张采购单不在途：{st}", "ใบสั่งซื้อนี้ไม่ได้อยู่ระหว่างส่ง: {st}"],
    "r.notin": ["{c} 不在这张采购单里", "{c} ไม่อยู่ในใบสั่งซื้อนี้"], "r.noitem_po": ["{c} 没有在途的采购单", "{c} ไม่มีใบสั่งซื้อที่กำลังส่ง"],
    "r.pick": ["这个物品在几张采购单里，选一张", "สินค้านี้อยู่หลายใบ เลือกหนึ่งใบ"], "r.plus": ["{c} +1", "{c} +1"], "r.zero": ["全部清零（扫一件加一件）", "ล้างเป็น 0 (สแกนทีละชิ้น)"],
    "r.noperm": ["你的账号没有「入库」权限", "บัญชีของคุณไม่มีสิทธิ์「รับเข้า」"], "r.nopur": ["采购模块没有打开", "ไม่ได้เปิดโมดูลจัดซื้อ"],
    // 状态
    "st.unpaid": ["未付款", "ยังไม่ชำระ"], "st.to_ship": ["待发货", "รอจัดส่ง"], "st.shipped": ["已发货", "จัดส่งแล้ว"], "st.completed": ["已完成", "สำเร็จ"],
    "st.cancelled": ["已取消", "ยกเลิกแล้ว"], "st.returned": ["退货/退款", "คืนสินค้า/คืนเงิน"], "st.delivery_failed": ["拒收/派送失败", "ปฏิเสธรับ/ส่งไม่สำเร็จ"],
    "st.quote": ["报价/预订单", "ใบเสนอราคา/สั่งจอง"], "st.other": ["其他", "อื่นๆ"],
    "js.todo": ["待打印", "รอพิมพ์"], "js.printing": ["打印中", "กำลังพิมพ์"], "js.post": ["后处理", "เก็บงาน"], "js.packed": ["已打包", "แพ็กแล้ว"],
    "js.done": ["已发货", "ส่งแล้ว"], "js.failed": ["打印失败", "พิมพ์ล้มเหลว"],
  };
  function T(k, v) {
    const e = L[k];
    let s = e ? e[TH() ? 1 : 0] : k;
    if (v) s = s.replace(/\{(\w+)\}/g, (m, x) => (v[x] != null ? v[x] : m));
    return s;
  }
  window.MT = T;
  const srv = (m) => (TH() && window.I18N && I18N.t ? I18N.t(String(m || "")) : String(m || ""));   // 后台的中文提示 → 泰文
  const stName = (st) => (L["st." + st] ? T("st." + st) : st);
  const jsName = (st) => (L["js." + st] ? T("js." + st) : st);
  const fmtT = (t) => { if (!t) return ""; const d = new Date(t * 1000); return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
  const nm = (zh, th) => (TH() && th ? th : zh || th || "");

  // ---------------- 接口 + 断网排队 ----------------
  async function api(url, opts = {}) {
    const o = { credentials: "same-origin", ...opts };
    if (o.json !== undefined) { o.method = o.method || "POST"; o.headers = { "Content-Type": "application/json" }; o.body = JSON.stringify(o.json); delete o.json; }
    let r;
    try { r = await fetch(url, o); } catch (e) { const x = new Error(T("net")); x.offline = true; throw x; }
    let data = null;
    try { data = await r.json(); } catch { /* 不是 JSON */ }
    if (r.status === 401 && data && data.login) { showLogin(); const x = new Error(T("login.t")); x.status = 401; throw x; }
    if (!r.ok || (data && data.error)) { const x = new Error(srv((data && data.error) || `HTTP ${r.status}`)); x.status = r.status; x.raw = data && data.error; throw x; }
    return data;
  }
  const QK = "m3d_queue", QF = "m3d_failed";
  const lget = (k) => { try { return JSON.parse(localStorage.getItem(k) || "[]"); } catch { return []; } };
  const lset = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 满了 */ } };
  // 能排队的写操作：网络断了先存起来
  async function send(url, body, label) {
    try { return await api(url, { json: body }); }
    catch (e) {
      if (!e.offline) throw e;
      const q = lget(QK); q.push({ url, body, label: label || url, at: Date.now() }); lset(QK, q);
      qbadge();
      return { queued: true };
    }
  }
  let flushing = false;
  async function flush() {
    if (flushing) return;
    let q = lget(QK);
    if (!q.length) return;
    flushing = true;
    let n = 0;
    try {
      while (q.length) {
        const it = q[0];
        try { await api(it.url, { json: it.body }); n++; }
        catch (e) {
          if (e.offline) break;
          if (e.status === 401) break;
          const f = lget(QF); f.push({ ...it, error: e.message }); lset(QF, f);
          SCAN.bad(); toast(T("q.rejected", { msg: `${it.label}：${e.message}` }), true, 9000);
        }
        q = lget(QK); q.shift(); lset(QK, q);
      }
    } finally { flushing = false; qbadge(); }
    if (n) { toast(T("q.sent", { n })); if (CUR && CUR.refresh) CUR.refresh(); }
  }
  setInterval(() => { if (navigator.onLine !== false) flush(); }, 10000);
  window.addEventListener("online", flush);
  function qbadge() {
    const p = lget(QK).length, f = lget(QF).length, b = $("#qbadge");
    b.classList.toggle("hidden", !p && !f);
    b.classList.toggle("fail", !!f);
    b.textContent = f ? `⚠ ${f}` : `⏳ ${p}`;
  }
  $("#qbadge").addEventListener("click", () => {
    const p = lget(QK), f = lget(QF);
    sheet(`<h3>${T("q.title")}</h3>
      ${f.length ? `<p class="bad"><b>${T("q.failed")}</b></p><ul class="list">${f.map((x) => `<li><div class="grow"><b data-notr>${esc(x.label)}</b><div class="small bad" data-notr>${esc(x.error)}</div></div></li>`).join("")}</ul>` : ""}
      ${p.length ? `<p><b>${T("q.pending")}</b></p><ul class="list">${p.map((x) => `<li><span class="grow" data-notr>${esc(x.label)}</span><span class="small muted">${fmtT(x.at / 1000)}</span></li>`).join("")}</ul>` : ""}
      <div class="col" style="margin-top:12px">${p.length ? `<button class="primary big" data-q="retry">${T("q.retry")}</button>` : ""}
        ${f.length ? `<button class="big danger" data-q="clear">${T("q.clear")}</button>` : ""}<button class="big" data-sheet-close>${T("close")}</button></div>`);
  });

  // ---------------- 小部件 ----------------
  function toast(msg, bad = false, ms = 3000) {
    const t = $("#toast");
    t.textContent = msg; t.className = "toast" + (bad ? " err" : "");
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), bad ? Math.max(ms, 6000) : ms);
  }
  function sheet(html) { $("#sheet-in").innerHTML = html; $("#sheet").classList.remove("hidden"); return $("#sheet-in"); }
  function closeSheet() { $("#sheet").classList.add("hidden"); $("#sheet-in").innerHTML = ""; }
  $("#sheet").addEventListener("click", async (e) => {
    if (e.target.id === "sheet" || e.target.closest("[data-sheet-close]")) { closeSheet(); return; }
    const q = e.target.closest("[data-q]");
    if (q && q.dataset.q === "retry") { closeSheet(); await flush(); }
    if (q && q.dataset.q === "clear") { lset(QF, []); qbadge(); closeSheet(); }
  });
  function confirmBox(msg) {
    return new Promise((ok) => {
      const s = sheet(`<p style="font-size:18px;font-weight:600" data-notr>${esc(msg)}</p><div class="row"><button class="big" data-c="0">${T("cancel")}</button><button class="big primary" data-c="1">${T("ok")}</button></div>`);
      s.querySelectorAll("[data-c]").forEach((b) => b.addEventListener("click", () => { closeSheet(); ok(b.dataset.c === "1"); }));
    });
  }
  const img = (src) => (src ? `<img src="${esc(src)}" alt="" loading="lazy">` : '<span class="noimg"></span>');
  function lastMsg(kind, text) { return text ? `<div class="lastmsg ${kind}" data-notr>${esc(text)}</div>` : ""; }
  // 拍照上传（打包照片）
  function takePhoto(oid) {
    return new Promise((done) => {
      const inp = $("#photo-in");
      inp.value = "";
      inp.onchange = async () => {
        const files = [...inp.files]; inp.onchange = null;
        if (!files.length) { done(null); return; }
        const fd = new FormData(); files.forEach((f) => fd.append("files", f)); fd.append("kind", "pack");
        try {
          const r = await api(`/api/mobile/orders/${oid}/photos`, { method: "POST", body: fd });
          SCAN.ok(); toast(T("p.photo_ok", { n: r.photos.length })); done(r.photos);
        } catch (e) { SCAN.bad(); toast(e.message, true); done(null); }
      };
      inp.click();
    });
  }

  // ---------------- 页面框架 ----------------
  let ME = null, PERMS = {}, INV = true, PUR = false, CUR = null;
  const view = () => $("#view");
  const SCREENS = {};
  function go(name, arg) {
    const h = "#/" + name + (arg ? "/" + encodeURIComponent(arg) : "");
    if (location.hash !== h) location.hash = h; else route();
  }
  function route() {
    if (!ME) return;
    const parts = (location.hash || "#/home").slice(2).split("/");
    const name = SCREENS[parts[0]] ? parts[0] : "home";
    const arg = parts[1] ? decodeURIComponent(parts[1]) : "";
    if (CUR && CUR.leave) CUR.leave();
    CUR = SCREENS[name];
    $("#title").textContent = name === "home" ? T("app") : T("t." + name);
    $("#back").classList.toggle("hidden", name === "home");
    view().scrollTop = 0;
    SCAN.on((code, src) => CUR.scan && CUR.scan(code, src));
    CUR.show(arg);
  }
  window.addEventListener("hashchange", route);
  $("#back").addEventListener("click", () => { if (history.length > 1) history.back(); else go("home"); });
  $("#lang").addEventListener("click", () => {
    const nl = TH() ? "zh" : "th";
    try { localStorage.setItem("ui_lang", nl); } catch { /* 忽略 */ }
    if (ME) api("/api/me/lang", { json: { lang: nl } }).catch(() => {});
    location.reload();
  });
  $("#lang").textContent = TH() ? "中文" : "ไทย";
  $("#scan-in").placeholder = T("ph.scan");
  $("#scan-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("#scan-in").value.trim();
    $("#scan-in").value = "";
    if (v) SCAN.feed(v, "manual");
  });
  $("#cam-toggle").addEventListener("click", () => SCAN.toggle());
  $("#photo-in").addEventListener("click", (e) => e.stopPropagation());

  // ---------------- 登录 ----------------
  function showLogin() {
    ME = null;
    SCAN.stop(false);
    $("#cam").classList.add("hidden");
    $("#title").textContent = T("app");
    $("#back").classList.add("hidden");
    $(".scanbar").classList.add("hidden");
    view().innerHTML = `<form class="card login" id="login-f"><h2>${T("login.t")}</h2>
      <label>${T("login.user")}</label><input id="lg-u" autocomplete="username" autocapitalize="off" required>
      <label>${T("login.pw")}</label><input id="lg-p" type="password" autocomplete="current-password" required>
      <button class="big primary" style="margin-top:16px">${T("login.go")}</button><div class="err-line" id="lg-err"></div></form>`;
    $("#login-f").addEventListener("submit", async (e) => {
      e.preventDefault();
      $("#lg-err").textContent = "";
      try {
        const r = await api("/api/auth/login", { json: { username: $("#lg-u").value.trim(), password: $("#lg-p").value, remember: true } });
        if (r.user && r.user.lang) { try { localStorage.setItem("ui_lang", r.user.lang); } catch { /* 忽略 */ } }
        if (r.user && r.user.lang && r.user.lang !== LANG) { location.reload(); return; }
        boot();
      } catch (err) { $("#lg-err").textContent = err.message; }
    });
  }

  async function boot() {
    let b;
    try { b = await api("/api/mobile/boot"); } catch (e) { if (e.status !== 401) { view().innerHTML = `<div class="card bad">${esc(e.message)}</div>`; setTimeout(boot, 5000); } return; }
    ME = b.user; PERMS = b.perms || {}; INV = !!b.inv; PUR = !!b.pur;
    $(".scanbar").classList.remove("hidden");
    if (SCAN.wanted()) SCAN.start(); else if (!SCAN.isApp()) $("#cam").classList.remove("hidden");
    qbadge(); flush();
    route();
  }

  // ---------------- 首页 ----------------
  SCREENS.home = {
    show() {
      const tiles = [["order", "🔎"], ["ship", "🚚"], ["pack", "✅"], ...(INV ? [["stock", "📦"], ["count", "🧮"], ["loc", "🗄"]] : []), ...(PUR ? [["rcv", "📥"]] : [])];
      view().innerHTML = `<div class="me"><span data-notr>👤 ${esc(ME.display_name || ME.username)}</span>
          <span class="row"><a href="/" class="small">${T("full")}</a><button class="sm" id="logout">${T("logout")}</button></span></div>
        <div class="tiles">${tiles.map(([k, ic]) => `<button class="tile" data-go="${k}"><span class="ti">${ic}</span>${T("t." + k)}<small>${T("t." + k + ".s")}</small></button>`).join("")}</div>
        <p class="hint small">${T("scan.any")}</p><div id="home-res"></div>`;
      view().querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => go(b.dataset.go)));
      $("#logout").addEventListener("click", async () => { try { await api("/api/auth/logout", { json: {} }); } catch { /* 忽略 */ } showLogin(); });
    },
    async scan(code) {
      try {
        const r = await api(`/api/mobile/resolve?code=${encodeURIComponent(code)}`);
        if (r.type === "order") { if (r.alert && r.alert.level === "error") SCAN.bad(); else SCAN.ok(); go("order", code); }
        else if (r.type === "item" || r.type === "sku") { SCAN.ok(); go("stock", code); }
        else if (["location", "shelf", "zone"].includes(r.type)) { SCAN.ok(); go("loc", code); }
        else { SCAN.bad(); $("#home-res").innerHTML = lastMsg("bad", T("unknown", { c: code })); }
      } catch (e) { SCAN.bad(); toast(e.message, true); }
    },
  };

  // ---------------- 查订单 ----------------
  function orderHtml(o, alert) {
    const late = o.ship_by && o.ship_by * 1000 < Date.now() && o.status === "to_ship";
    const counts = Object.entries(o.job_counts || {});
    return `${alert ? `<div class="banner ${alert.level}" data-notr>${esc(TH() ? alert.th : alert.zh)}</div>` : ""}
      <div class="card"><div class="row between wrap"><span class="mono" style="font-size:20px;font-weight:800" data-notr>${esc(o.order_no)}</span>
        <span class="chip ${esc(o.status)}">${esc(stName(o.status))}</span></div>
        <div class="kv" style="margin-top:6px">
          <span>${T("o.time")}</span><span data-notr>${esc(o.platform || "")} ${esc(o.shop || "")} · ${fmtT(o.order_time)}</span>
          ${o.tracking_no ? `<span>${T("o.tracking")}</span><span class="mono" data-notr>${esc(o.tracking_no)}</span>` : ""}
          ${o.carrier ? `<span>${T("o.carrier")}</span><span data-notr>${esc(o.carrier)}</span>` : ""}
          <span>${T("o.buyer")}</span><span data-notr>${esc(o.receiver || o.buyer || "")}</span>
          ${o.ship_by ? `<span>${T("o.shipby")}</span><span class="${late ? "bad" : ""}">${fmtT(o.ship_by)}${late ? " · " + T("o.late") : ""}</span>` : ""}
          ${o.is_cod ? `<span>${T("o.cod")}</span><span><b>COD</b>${o.cod ? " ฿" + esc(o.cod) : ""}</span>` : ""}
          ${o.hold ? `<span></span><span class="warn"><b>${T("o.hold")}</b> <span data-notr>${esc(o.hold_reason || "")}</span></span>` : ""}
          ${o.handover ? `<span>${T("o.handover")}</span><span>#${o.handover.id} <span data-notr>${esc(o.handover.carrier || "")}</span> · ${o.handover.closed_at ? T("o.closed") : T("o.open")}</span>` : ""}
        </div>
        ${o.custom_note ? `<div class="note"><span class="small">${T("o.custom")}</span><br><span data-notr>${esc(o.custom_note)}</span></div>` : ""}
        ${o.buyer_note ? `<div class="small"><b>${T("o.bnote")}：</b><span data-notr>${esc(o.buyer_note)}</span></div>` : ""}
      </div>
      <div class="card"><h3>${T("o.items")}</h3>${(o.items || []).map((i) => `<div class="item">${img(i.img)}<div class="grow">
          <div class="mono" data-notr><b>${esc(i.sku || "")}</b></div><div class="nm" data-notr>${esc(i.name || "")}</div>
          <div class="small muted" data-notr>${esc(i.variation || nm(i.color, i.color_th) || "")}</div></div><span class="q">×${esc(i.qty)}</span></div>`).join("")}</div>
      <div class="card"><h3>${T("o.prod")}</h3>${counts.length ? `<div class="row wrap">${counts.map(([k, n]) => `<span class="chip">${esc(jsName(k))} ${n}</span>`).join("")}</div>
        <ul class="list small">${(o.jobs || []).map((j) => `<li><span class="mono grow" data-notr>${esc(j.sku || "")} ×${esc(j.qty)}</span><span>${esc(jsName(j.status))}</span>
          <span class="muted" data-notr>${esc(j.printer_code || "")}</span></li>`).join("")}</ul>` : `<p class="muted small">${T("o.nojobs")}</p>`}</div>
      <div class="card"><div class="row between"><h3>${T("o.photos")} (${o.photos || 0})</h3></div><div class="thumbs" id="o-photos"></div></div>
      <div class="col">${o.status === "to_ship" ? `<button class="big primary" id="o-pack">${T("o.pack")}</button>` : ""}<button class="big" id="o-photo">${T("o.photo")}</button></div>`;
  }
  async function loadPhotos(oid, box) {
    if (!box) return;
    try {
      const r = await api(`/api/mobile/orders/${oid}/photos`);
      box.innerHTML = r.photos.map((p) => `<a href="${esc(p.url)}" target="_blank"><img src="${esc(p.url)}" alt=""></a>`).join("");
    } catch { /* 没有也行 */ }
  }
  SCREENS.order = {
    o: null,
    show(arg) {
      this.o = null;
      view().innerHTML = `<p class="hint"><span class="big-ic">🔎</span>${T("o.scan")}</p><div id="o-out"></div>`;
      if (arg) this.scan(arg, "manual");
    },
    refresh() { if (this.o) this.open(this.o.order_no, false); },
    async open(code, beep = true) {
      const r = await api(`/api/mobile/resolve?fresh=1&code=${encodeURIComponent(code)}`);
      return this.render(r, code, beep);
    },
    render(r, code, beep) {
      const out = view();
      if (r.type === "order") {
        this.o = r.order;
        if (beep) { if (r.alert && r.alert.level === "error") SCAN.bad(); else if (r.alert) SCAN.warn(); else SCAN.ok(); }
        out.innerHTML = orderHtml(r.order, r.alert);
        loadPhotos(r.order.id, $("#o-photos"));
        const pk = $("#o-pack"); if (pk) pk.addEventListener("click", () => go("pack", r.order.order_no));
        $("#o-photo").addEventListener("click", async () => { if (await takePhoto(r.order.id)) this.refresh(); });
        return true;
      }
      if (r.type === "item" || r.type === "sku") {
        if (beep) SCAN.warn();
        out.innerHTML = `<div class="card"><p>${T("o.isitem")}：<b class="mono" data-notr>${esc(code)}</b></p><button class="big primary" id="o-go">${T("go.stock")}</button></div>`;
        $("#o-go").addEventListener("click", () => go("stock", code));
        return true;
      }
      if (["location", "shelf", "zone"].includes(r.type)) {
        if (beep) SCAN.warn();
        out.innerHTML = `<div class="card"><p>${T("o.isloc")}：<b class="mono" data-notr>${esc(code)}</b></p><button class="big primary" id="o-go">${T("go.loc")}</button></div>`;
        $("#o-go").addEventListener("click", () => go("loc", code));
        return true;
      }
      return false;
    },
    async scan(code, src) {
      try {
        const r = await api(`/api/mobile/resolve?fresh=1&code=${encodeURIComponent(code)}`);
        if (this.render(r, code, true)) return;
        // 认不出来：手输的按订单号 / 买家模糊查
        if (src === "manual" && code.length >= 2) {
          const s = await api(`/api/mobile/orders?q=${encodeURIComponent(code)}`);
          if (!s.orders.length) { SCAN.bad(); view().innerHTML = lastMsg("bad", T("o.none")); return; }
          if (s.orders.length === 1) { await this.open(s.orders[0].order_no); return; }
          SCAN.ok();
          view().innerHTML = `<p class="small muted">${T("o.found", { n: s.orders.length })}</p><div class="card"><ul class="list">${s.orders.map((o) => `<li class="tap" data-no="${esc(o.order_no)}">
            <div class="grow"><div class="mono" data-notr><b>${esc(o.order_no)}</b></div><div class="small muted" data-notr>${esc(o.receiver || o.buyer || "")} · ${esc(o.platform || "")} · ${fmtT(o.order_time)}</div></div>
            <span class="chip ${esc(o.status)}">${esc(stName(o.status))}</span></li>`).join("")}</ul></div>`;
          view().querySelectorAll("[data-no]").forEach((li) => li.addEventListener("click", () => this.open(li.dataset.no, false).catch((e) => toast(e.message, true))));
          return;
        }
        SCAN.bad(); view().innerHTML = lastMsg("bad", T("unknown", { c: code }));
      } catch (e) { SCAN.bad(); toast(e.message, true); }
    },
  };

  // ---------------- 扫码发货交接 ----------------
  SCREENS.ship = {
    h: null, msg: null, pend: [],
    async show() {
      this.msg = null; this.pend = [];
      const hid = +(localStorage.getItem("m3d_ship_h") || 0);
      if (hid) {
        try { const h = await api(`/api/handovers/${hid}`); if (!h.closed_at) { this.h = h; this.render(); return; } } catch (e) { if (e.offline && this.h) { this.render(); return; } }
        localStorage.removeItem("m3d_ship_h");
      }
      this.h = null;
      this.pick();
    },
    refresh() { if (this.h) api(`/api/handovers/${this.h.id}`).then((h) => { this.h = h; this.pend = []; this.render(); }).catch(() => {}); },
    async pick() {
      view().innerHTML = `<p class="muted">${T("loading")}</p>`;
      let r;
      try { r = await api("/api/mobile/carriers"); } catch (e) { view().innerHTML = lastMsg("bad", e.message); return; }
      view().innerHTML = `${r.open.length ? `<div class="card"><h3>${T("s.open")}</h3><ul class="list">${r.open.map((h) => `<li class="tap" data-hid="${h.id}">
          <div class="grow"><b data-notr>#${h.id} ${esc(h.carrier || T("s.any"))}</b><div class="small muted" data-notr>${esc(h.username || "")} · ${fmtT(h.created_at)}</div></div>
          <span class="chip">${h.count}</span><button class="sm primary">${T("s.continue")}</button></li>`).join("")}</ul></div>` : ""}
        <div class="card"><h3>${T("s.pick")}</h3><div class="col">${r.carriers.map((c) => `<button class="big" data-car="${esc(c.carrier)}"><span data-notr>${esc(c.carrier)}</span>
          <span class="small muted"> · ${T("s.toship", { n: c.to_ship })}</span></button>`).join("")}
          <div class="row"><input id="s-car" placeholder="${esc(T("s.carrier_ph"))}" data-notr><button class="primary" id="s-go">${T("s.start")}</button></div>
          <button class="big" data-car="">${T("s.any")}</button></div></div>`;
      view().querySelectorAll("[data-hid]").forEach((li) => li.addEventListener("click", () => this.openH(+li.dataset.hid)));
      view().querySelectorAll("[data-car]").forEach((b) => b.addEventListener("click", () => this.start(b.dataset.car)));
      $("#s-go").addEventListener("click", () => { const v = $("#s-car").value.trim(); if (v) this.start(v); });
    },
    async openH(id) {
      try { this.h = await api(`/api/handovers/${id}`); localStorage.setItem("m3d_ship_h", id); this.render(); } catch (e) { toast(e.message, true); }
    },
    async start(carrier) {
      try { this.h = await api("/api/handovers", { json: { carrier } }); localStorage.setItem("m3d_ship_h", this.h.id); SCAN.ok(); this.render(); }
      catch (e) { SCAN.bad(); toast(e.message, true); }
    },
    render() {
      const h = this.h;
      if (!h) return this.pick();
      const orders = [...(h.orders || [])].reverse();
      view().innerHTML = `<div class="card"><div class="row between"><b data-notr>#${h.id} ${esc(h.carrier || T("s.any"))}</b><button class="sm" id="s-sw">${T("s.switch")}</button></div>
          <div class="count">${h.count || 0}${this.pend.length ? ` <span class="small warn">+${this.pend.length}⏳</span>` : ""}</div>
          <p class="hint small" style="padding:4px">${T("s.scan")}</p>
          ${this.msg ? lastMsg(this.msg[0], this.msg[1]) : ""}</div>
        <div class="card"><ul class="list">${this.pend.map((c) => `<li class="warn" data-notr>${esc(T("s.queued", { c }))}</li>`).join("")}
          ${orders.map((o) => `<li><div class="grow"><div class="mono" data-notr><b>${esc(o.tracking_no || o.order_no)}</b></div>
            <div class="small muted" data-notr>${esc(o.order_no)} · ${esc(o.platform || "")} · ${esc(o.receiver || o.buyer || "")}</div></div>
            ${o.status !== "to_ship" ? `<span class="chip ${esc(o.status)}">${esc(stName(o.status))}</span>` : ""}
            <button class="sm danger" data-rm="${o.id}" data-no="${esc(o.order_no)}">✕</button></li>`).join("") || (this.pend.length ? "" : `<li class="muted">${T("s.empty")}</li>`)}</ul></div>
        <div class="col"><button class="big okb" id="s-close" ${h.count ? "" : "disabled"}>${T("s.close")}</button>
          <a class="btnlink" href="/print/handover?id=${h.id}" target="_blank">${T("s.print")}</a></div>`;
      $("#s-sw").addEventListener("click", () => { localStorage.removeItem("m3d_ship_h"); this.h = null; this.pick(); });
      view().querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", async () => {
        if (!(await confirmBox(T("s.remove_q", { no: b.dataset.no })))) return;
        try { this.h = await api(`/api/handovers/${h.id}/remove`, { json: { order_id: +b.dataset.rm } }); this.render(); } catch (e) { toast(e.message, true); }
      }));
      $("#s-close").addEventListener("click", async (e) => {
        if (!(await confirmBox(T("s.close_q", { n: h.count })))) return;
        e.target.disabled = true;
        try {
          const r = await api(`/api/handovers/${h.id}/close`, { json: {} });
          SCAN.ok(); localStorage.removeItem("m3d_ship_h");
          view().innerHTML = `<div class="banner ok">${T("s.closed", { n: r.shipped })}</div>
            <div class="col"><a class="btnlink" href="/print/handover?id=${h.id}" target="_blank">${T("s.print")}</a>
            <button class="big primary" id="s-new">${T("s.pick")}</button></div>`;
          this.h = null;
          $("#s-new").addEventListener("click", () => this.pick());
        } catch (err) { SCAN.bad(); toast(err.message, true); e.target.disabled = false; }
      });
    },
    async scan(code) {
      if (!this.h) {                       // 还没选物流：扫的是面单就按订单的物流开交接单
        try {
          const r = await api(`/api/mobile/resolve?code=${encodeURIComponent(code)}`);
          if (r.type !== "order") { SCAN.bad(); toast(T("unknown", { c: code }), true); return; }
          await this.start(r.order.carrier || "");
          if (!this.h) return;
        } catch (e) { SCAN.bad(); toast(e.message, true); return; }
      }
      try {
        const r = await send(`/api/handovers/${this.h.id}/scan`, { code }, `${T("t.ship")} #${this.h.id}: ${code}`);
        if (r.queued) { SCAN.warn(); this.pend.push(code); this.msg = ["warn", T("offline.q")]; this.render(); return; }
        this.h = r.handover;
        const no = r.order.tracking_no || r.order.order_no;
        if (r.warn && r.warn.length) { SCAN.warn(); this.msg = ["warn", `${no}：${r.warn.map(srv).join("；")}`]; }
        else { SCAN.ok(); this.msg = ["ok", T("s.added", { no })]; }
      } catch (e) {
        if (/已经扫过了/.test(e.raw || "")) { SCAN.warn(); this.msg = ["warn", e.message]; }
        else { SCAN.bad(); this.msg = ["bad", e.message]; }
      }
      this.render();
    },
  };

  // ---------------- 验货 ----------------
  SCREENS.pack = {
    pk: null, msg: null, log: [], phase: "",
    show(arg) {
      this.pk = null; this.msg = null; this.log = []; this.phase = "";
      this.render();
      if (arg) this.scan(arg);
    },
    done(k) { return (this.pk.got[k] || 0) >= this.pk.need[k]; },
    render() {
      const pk = this.pk;
      if (!pk) {
        view().innerHTML = `${this.msg ? lastMsg(this.msg[0], this.msg[1]) : ""}<p class="hint"><span class="big-ic">✅</span>${T("p.wait")}</p>`;
        return;
      }
      const o = pk.order;
      if (this.phase === "photo") {
        view().innerHTML = `<div class="banner ok" data-notr>${esc(this.msg ? this.msg[1] : "")}</div>
          <div class="card"><p style="font-size:18px">${T("p.photo_q")}</p><p class="mono" data-notr>${esc(o.order_no)}</p>
          <div class="col"><button class="big primary" id="p-ph">${T("p.photo")}</button><button class="big" id="p-skip">${T("p.skip")}</button></div></div>`;
        $("#p-ph").addEventListener("click", async () => { if (await takePhoto(o.id)) this.next(); });
        $("#p-skip").addEventListener("click", () => this.next());
        return;
      }
      const keys = Object.keys(pk.need);
      const left = keys.reduce((s, k) => s + Math.max(0, pk.need[k] - (pk.got[k] || 0)), 0);
      const notReady = (o.jobs || []).filter((j) => !["post", "packed", "done"].includes(j.status));
      const rows = [];
      const shown = new Set();
      for (const i of o.items) {
        const k = (i.sku || "").toUpperCase();
        if (shown.has(k)) continue;
        shown.add(k);
        const need = pk.need[k], got = Math.min(pk.got[k] || 0, need), m = pk.mode[k];
        const act = m === "scan" ? `<div class="small muted">${T("p.scanit")}</div><button class="sm" data-plus="${esc(k)}">${T("p.plus")}</button>`
          : m === "tap" ? (got >= need ? '<span class="ok" style="font-size:24px">✓</span>' : `<button class="primary" data-tap="${esc(k)}">${T("p.tap")}</button>`)
          : `<span class="small muted">${T("p.none")}</span>`;
        rows.push(`<div class="item ${got >= need ? "done" : ""}">${img(i.img)}<div class="grow"><div class="mono" data-notr><b>${esc(i.sku || "")}</b></div>
          <div class="nm" data-notr>${esc(i.name || "")}</div><div class="small muted">${esc(i.variation || i.color || "")}</div>
          <div class="prog"><i style="width:${need ? Math.round(100 * got / need) : 100}%"></i></div></div>
          <div style="text-align:right"><div class="q">${got}/${need}</div>${act}</div></div>`);
      }
      view().innerHTML = `${this.msg ? lastMsg(this.msg[0], this.msg[1]) : ""}
        <div class="card"><div class="row between wrap"><span class="mono" style="font-size:18px;font-weight:800" data-notr>${esc(o.order_no)}</span>
          <span class="chip ${esc(o.status)}">${esc(stName(o.status))}</span></div>
          <div class="small muted" data-notr>${esc(o.platform || "")} · ${esc(o.receiver || o.buyer || "")}${o.tracking_no ? " · " + esc(o.tracking_no) : ""}</div>
          ${o.status !== "to_ship" ? `<div class="banner warn">${T("p.notship", { st: stName(o.status) })}</div>` : ""}
          ${o.hold ? `<div class="banner warn">${T("o.hold")}</div>` : ""}
          ${o.custom_note ? `<div class="note"><span class="small">${T("o.custom")}</span><br><span data-notr>${esc(o.custom_note)}</span></div>` : ""}
          ${o.buyer_note ? `<div class="small"><b>${T("o.bnote")}：</b><span data-notr>${esc(o.buyer_note)}</span></div>` : ""}
          ${o.box && o.box.code ? `<div class="small">${T("p.box")}：<b data-notr>${esc(o.box.code)}</b></div>` : ""}
          ${notReady.length ? `<div class="banner warn">${T("p.jobs", { n: notReady.length })}</div>` : ""}</div>
        <div class="card">${rows.join("")}</div>
        <p style="text-align:center;font-weight:700;font-size:18px" class="${left ? "warn" : "ok"}">${left ? T("p.left", { n: left }) : T("p.all")}</p>
        ${this.log.length ? `<div class="card small">${this.log.slice(-4).reverse().map((x) => `<div class="bad" data-notr>✕ ${esc(x)}</div>`).join("")}</div>` : ""}
        <div class="col"><button class="big okb" id="p-done" ${left ? "disabled" : ""}>${T("p.done")}</button><button class="big" id="p-reset">${T("p.reset")}</button></div>`;
      view().querySelectorAll("[data-plus]").forEach((b) => b.addEventListener("click", () => this.item(b.dataset.plus)));
      view().querySelectorAll("[data-tap]").forEach((b) => b.addEventListener("click", () => { const k = b.dataset.tap; this.pk.got[k] = this.pk.need[k]; SCAN.ok(); this.msg = ["ok", "✔ " + k]; this.render(); }));
      $("#p-reset").addEventListener("click", () => { this.pk = null; this.msg = null; this.log = []; this.render(); });
      $("#p-done").addEventListener("click", (e) => this.finish(e.target));
    },
    item(k) {
      if (this.done(k)) { SCAN.bad(); this.msg = ["bad", T("p.extra", { c: k, n: this.pk.need[k] })]; this.log.push(this.msg[1]); }
      else { this.pk.got[k] = (this.pk.got[k] || 0) + 1; SCAN.ok(); this.msg = ["ok", `✔ ${k}  ${this.pk.got[k]}/${this.pk.need[k]}`]; }
      this.render();
    },
    async finish(btn) {
      btn.disabled = true;
      const o = this.pk.order;
      try {
        const r = await send("/api/pack/done", { order_id: o.id }, `${T("t.pack")}: ${o.order_no}`);
        SCAN.ok();
        this.msg = ["ok", r.queued ? T("offline.q") : T("p.ok", { n: r.packed })];
        this.phase = "photo";
        this.render();
      } catch (e) { SCAN.bad(); this.msg = ["bad", e.message]; btn.disabled = false; this.render(); }
    },
    next() { this.pk = null; this.phase = ""; this.log = []; this.render(); },
    async lookup(code) {
      const o = await api(`/api/pack/lookup?code=${encodeURIComponent(code)}`);
      const pk = { order: o, need: {}, got: {}, mode: {} };
      o.items.forEach((i) => {
        const k = (i.sku || "").toUpperCase();
        pk.need[k] = (pk.need[k] || 0) + (i.qty || 1);
        pk.mode[k] = pk.mode[k] === "scan" || i.check === "scan" ? "scan" : pk.mode[k] === "tap" || i.check === "tap" ? "tap" : (i.check || "tap");
      });
      Object.keys(pk.need).forEach((k) => { if (pk.mode[k] === "none") pk.got[k] = pk.need[k]; });
      return pk;
    },
    async scan(code) {
      if (this.phase === "photo") this.next();
      const k = code.toUpperCase();
      if (this.pk && this.pk.need[k] !== undefined) { this.item(k); return; }
      try {
        const prev = this.pk;
        const incomplete = prev && Object.keys(prev.need).some((x) => !this.done(x));
        this.pk = await this.lookup(code);
        this.log = [];
        const anyScan = Object.values(this.pk.mode).includes("scan");
        if (incomplete) { SCAN.warn(); this.msg = ["warn", T("p.switch", { no: this.pk.order.order_no })]; }
        else { SCAN.ok(); this.msg = ["ok", anyScan ? T("p.found_scan") : T("p.found_tap")]; }
        if (this.pk.order.status !== "to_ship" || this.pk.order.hold) SCAN.warn();
      } catch (e) {
        SCAN.bad();
        if (this.pk && e.status === 404) { this.msg = ["bad", T("p.wrong", { c: code })]; this.log.push(this.msg[1]); }
        else this.msg = ["bad", e.message];
      }
      this.render();
    },
  };

  // ---------------- 库存 ----------------
  SCREENS.stock = {
    r: null, act: "in", msg: null,
    show(arg) {
      this.r = null; this.msg = null;
      if (!INV) { view().innerHTML = lastMsg("bad", T("k.noinv")); return; }
      view().innerHTML = `<p class="hint"><span class="big-ic">📦</span>${T("k.scan")}</p>`;
      if (arg) this.scan(arg);
    },
    refresh() { if (this.r) { this.msg = null; this.load(this.r.code, false); } },
    async load(code, beep = true) {
      const r = await api(`/api/mobile/resolve?prefer=item&code=${encodeURIComponent(code)}`);
      if (r.type === "order" || ["location", "shelf", "zone"].includes(r.type)) { if (beep) SCAN.warn(); this.r = null; this.other(r, code); return; }
      if (r.type === "unknown") { if (beep) SCAN.bad(); view().innerHTML = lastMsg("bad", T("unknown", { c: code })); return; }
      if (beep) SCAN.ok();
      this.r = r;
      this.render();
    },
    other(r, code) {
      const isOrder = r.type === "order";
      view().innerHTML = `<div class="card"><p>${isOrder ? "🧾" : T("o.isloc")} <b class="mono" data-notr>${esc(code)}</b></p>
        <button class="big primary" id="k-go">${isOrder ? T("go.order") : T("go.loc")}</button></div>`;
      $("#k-go").addEventListener("click", () => go(isOrder ? "order" : "loc", code));
    },
    render() {
      const r = this.r;
      if (r.type === "sku") {
        const s = r.sku;
        view().innerHTML = `<div class="card"><div class="item">${img(s.img)}<div class="grow"><div class="mono" data-notr><b>${esc(s.sku)}</b></div>
          <div class="nm" data-notr>${esc(nm(s.name_zh, s.title_th))}</div><div class="small muted" data-notr>${esc(s.opt1_zh || "")}</div></div></div>
          <p class="warn">${T("k.nofile")}</p><p class="small">${T("k.free")}：<b>${esc(s.free_stock)}</b></p>
          <button class="big primary" id="k-create">${T("k.create")}</button></div>`;
        $("#k-create").addEventListener("click", async (e) => {
          e.target.disabled = true;
          try { await api("/api/inv/items", { json: { code: s.sku, name_zh: s.name_zh || s.sku, name_th: s.title_th || "", category: "goods", unit: "件" } }); await this.load(s.sku, false); }
          catch (err) { toast(err.message, true); e.target.disabled = false; }
        });
        return;
      }
      const it = r.item;
      const acts = [["in", "k.in", "inv.in"], ["out", "k.out", "inv.out"], ["set", "k.set", "inv.adjust"]].filter((a) => PERMS[a[2]] !== false);
      if (!acts.find((a) => a[0] === this.act)) this.act = (acts[0] || ["in"])[0];
      const reasons = this.act === "in" ? [["purchase", "k.r.purchase"], ["return", "k.r.return"]] : this.act === "out" ? [["issue", "k.r.issue"], ["scrap", "k.r.scrap"]] : [];
      view().innerHTML = `${this.msg ? lastMsg(this.msg[0], this.msg[1]) : ""}
        <div class="card"><div class="item">${img(it.img)}<div class="grow"><div class="mono" data-notr><b>${esc(it.code)}</b></div>
          <div class="nm" data-notr>${esc(nm(it.name_zh, it.name_th))}</div><div class="small muted">${esc(TH() ? it.category_th : it.category_zh)}</div></div>
          <div style="text-align:right"><div class="small muted">${T("k.qty")}</div><div class="q" style="font-size:30px">${esc(+(+it.qty).toFixed(3))}</div><div class="small" data-notr>${esc(it.unit || "")}</div></div></div>
          <div class="kv"><span>${T("k.loc")}</span><span>${it.loc ? `<b class="loc" data-notr>${esc(it.loc.code)}</b> <span class="small muted">${esc(TH() ? it.loc.human_th : it.loc.human_zh)}</span>` : `<span class="muted">${T("k.noloc")}</span>`}</span>
          ${it.free_stock != null ? `<span>${T("k.free")}</span><span>${esc(it.free_stock)}</span>` : ""}</div>
          ${it.low ? `<div class="banner warn">${T("k.low")}</div>` : ""}</div>
        ${acts.length ? `<div class="card col"><div class="seg">${acts.map(([k, t]) => `<button data-act="${k}" class="${this.act === k ? "on" : ""}">${T(t)}</button>`).join("")}</div>
          ${reasons.length ? `<select id="k-kind">${reasons.map(([k, t]) => `<option value="${k}">${T(t)}</option>`).join("")}</select>` : `<div class="small muted">${T("k.actual")}</div>`}
          <div class="step"><button id="k-minus">−</button><input id="k-qty" type="number" inputmode="decimal" value="${this.act === "set" ? esc(+(+it.qty).toFixed(3)) : 1}"><button id="k-plus">+</button></div>
          <input id="k-note" placeholder="${esc(T("k.note"))}">
          <button class="big primary" id="k-go">${T("k.submit")}</button></div>` : ""}`;
      view().querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", () => { this.act = b.dataset.act; this.msg = null; this.render(); }));
      if (!acts.length) return;
      const q = $("#k-qty");
      $("#k-minus").addEventListener("click", () => { q.value = Math.max(0, (+q.value || 0) - 1); });
      $("#k-plus").addEventListener("click", () => { q.value = (+q.value || 0) + 1; });
      $("#k-go").addEventListener("click", (e) => this.submit(e.target));
    },
    async submit(btn) {
      const it = this.r.item, v = +$("#k-qty").value, note = $("#k-note").value.trim();
      let kind, qty;
      if (this.act === "set") {
        if (!isFinite(v) || v < 0) return;
        qty = +(v - (+it.qty || 0)).toFixed(3);
        if (!qty) { toast(T("k.same")); return; }
        kind = "adjust";
      } else {
        if (!isFinite(v) || v <= 0) return;
        qty = v; kind = $("#k-kind").value;
        if (kind === "scrap" && !note) { toast(T("k.scrapnote"), true); $("#k-note").focus(); return; }
      }
      btn.disabled = true;
      const body = { kind, lines: [{ item_id: it.id, qty }], note: note || (kind === "adjust" ? T("k.adjnote") : "📱") };
      try {
        const r = await send("/api/inv/docs", body, `${T("k." + this.act)} ${it.code} ${this.act === "set" ? "→ " + v : "×" + v}`);
        SCAN.ok();
        this.msg = r.queued ? ["warn", T("offline.q")] : ["ok", T("k.done", { name: it.code, q: this.act === "set" ? "= " + v : (this.act === "in" ? "+" : "−") + v })];
        if (!r.queued) { await this.load(it.code, false); return; }
      } catch (e) { SCAN.bad(); this.msg = ["bad", e.message]; }
      btn.disabled = false;
      this.render();
    },
    async scan(code) {
      try { this.msg = null; await this.load(code); } catch (e) { SCAN.bad(); toast(e.message, true); }
    },
  };

  // ---------------- 盘点 ----------------
  SCREENS.count = {
    doc: null, msg: null,
    async show() {
      this.msg = null;
      if (!INV) { view().innerHTML = lastMsg("bad", T("k.noinv")); return; }
      const did = +(localStorage.getItem("m3d_count_doc") || 0);
      this.doc = null;
      if (did) {
        try { const r = await api(`/api/inv/docs/${did}`); if (r.doc && r.doc.status === "draft") this.doc = r.doc; } catch { /* 没了 */ }
        if (!this.doc) localStorage.removeItem("m3d_count_doc");
      }
      this.render();
    },
    area() { return ((this.doc && this.doc.ref) || "").replace(/^area:/, ""); },
    render() {
      const d = this.doc;
      if (!d) { view().innerHTML = `${this.msg ? lastMsg(this.msg[0], this.msg[1]) : ""}<p class="hint"><span class="big-ic">🧮</span>${T("c.scan")}</p>`; return; }
      view().innerHTML = `${this.msg ? lastMsg(this.msg[0], this.msg[1]) : ""}
        <div class="card"><div class="row between"><span>${T("c.area")}：<b class="loc" data-notr>${esc(this.area() || "—")}</b></span><span class="small muted mono" data-notr>${esc(d.no)}</span></div></div>
        <div class="card"><ul class="list">${d.lines.map((l) => {
          const diff = l.counted != null ? +(l.counted - (l.now_qty ?? l.expected)).toFixed(3) : null;
          return `<li><div class="grow"><div class="mono" data-notr><b>${esc(l.code)}</b></div><div class="small" data-notr>${esc(nm(l.name_zh, l.name_th))}</div>
            <div class="small muted">${T("c.book")} ${esc(+(+(l.now_qty ?? l.expected)).toFixed(3))} ${esc(l.unit || "")}${diff ? ` · <b class="${diff < 0 ? "bad" : "warn"}">${T("c.diff")} ${diff > 0 ? "+" : ""}${diff}</b>` : ""}</div></div>
            <div class="step" style="width:150px"><button class="sm" data-dec="${l.id}">−</button><input type="number" inputmode="decimal" data-cnt="${l.id}" value="${l.counted ?? ""}" placeholder="—" style="min-height:40px;font-size:18px;padding:4px"><button class="sm" data-inc="${l.id}">+</button></div></li>`;
        }).join("")}</ul></div>
        <label class="row small" style="margin:6px 4px"><input type="checkbox" id="c-zero" style="width:auto;min-height:0"> ${T("c.zero")}</label>
        <div class="col"><button class="big" id="c-save">${T("c.save")}</button>
          ${PERMS["inv.adjust"] !== false ? `<button class="big okb" id="c-confirm">${T("c.confirm")}</button>` : ""}
          <button class="big" id="c-new">${T("c.new")}</button></div>`;
      const line = (id) => d.lines.find((l) => l.id === +id);
      view().querySelectorAll("[data-inc]").forEach((b) => b.addEventListener("click", () => { const l = line(b.dataset.inc); l.counted = (+l.counted || 0) + 1; this.keep(); this.render(); }));
      view().querySelectorAll("[data-dec]").forEach((b) => b.addEventListener("click", () => { const l = line(b.dataset.dec); l.counted = Math.max(0, (+l.counted || 0) - 1); this.keep(); this.render(); }));
      view().querySelectorAll("[data-cnt]").forEach((inp) => inp.addEventListener("change", () => { const l = line(inp.dataset.cnt); l.counted = inp.value === "" ? null : +inp.value; this.keep(); }));
      $("#c-save").addEventListener("click", (e) => this.save(e.target));
      const cf = $("#c-confirm"); if (cf) cf.addEventListener("click", (e) => this.confirm(e.target));
      $("#c-new").addEventListener("click", () => { localStorage.removeItem("m3d_count_doc"); this.doc = null; this.msg = null; this.render(); });
    },
    keep() { try { localStorage.setItem("m3d_count_lines_" + this.doc.id, JSON.stringify(this.doc.lines.map((l) => [l.id, l.counted]))); } catch { /* 忽略 */ } },
    counts() {
      const zero = $("#c-zero") && $("#c-zero").checked;
      const out = {};
      this.doc.lines.forEach((l) => { if (l.counted != null && l.counted !== "") out[l.id] = l.counted; else if (zero) { out[l.id] = 0; l.counted = 0; } });
      return out;
    },
    async save(btn) {
      btn.disabled = true;
      try { const r = await api(`/api/inv/stocktake/${this.doc.id}/save`, { json: { counts: this.counts() } }); this.doc = r.doc; this.msg = ["ok", T("c.saved")]; SCAN.ok(); }
      catch (e) { SCAN.bad(); this.msg = ["bad", e.message]; }
      this.render();
    },
    async confirm(btn) {
      if (!(await confirmBox(T("c.confirm_q")))) return;
      btn.disabled = true;
      try {
        await api(`/api/inv/stocktake/${this.doc.id}/save`, { json: { counts: this.counts() } });
        const r = await api(`/api/inv/stocktake/${this.doc.id}/confirm`, { json: {} });
        const n = (r.doc.lines || []).filter((l) => l.qty && Math.abs(l.qty) > 1e-6).length;
        SCAN.ok(); localStorage.removeItem("m3d_count_doc"); this.doc = null; this.msg = ["ok", T("c.confirmed", { n })];
      } catch (e) { SCAN.bad(); this.msg = ["bad", e.message]; }
      this.render();
    },
    async start(code) {
      const r = await api("/api/inv/stocktake", { json: { area: code, note: "📱" } });
      this.doc = r.doc;
      localStorage.setItem("m3d_count_doc", r.doc.id);
      SCAN.ok(); this.msg = null; this.render();
    },
    async scan(code) {
      const k = code.toUpperCase();
      if (this.doc) {
        const l = this.doc.lines.find((x) => String(x.code).toUpperCase() === k);
        if (l) { l.counted = (+l.counted || 0) + 1; this.keep(); SCAN.ok(); this.msg = ["ok", `✔ ${l.code}  ${l.counted}`]; this.render(); return; }
      }
      try {
        const r = await api(`/api/mobile/resolve?prefer=location&code=${encodeURIComponent(code)}`);
        if (["location", "shelf", "zone"].includes(r.type)) {
          const ac = r.type === "location" ? r.location.code : String(r.code || "").toUpperCase();
          if (this.doc && ac === this.area().toUpperCase()) { SCAN.ok(); return; }
          await this.start(ac);
          return;
        }
        if (r.type === "item") {
          SCAN.warn();
          this.msg = this.doc ? ["warn", T("c.notin", { c: r.item.code, w: r.item.loc ? T("c.at", { l: r.item.loc.code }) : "" })] : ["warn", T("c.needitem")];
        } else { SCAN.bad(); this.msg = ["bad", T("unknown", { c: code })]; }
      } catch (e) { SCAN.bad(); this.msg = ["bad", e.message]; }
      this.render();
    },
  };

  // ---------------- 货位 ----------------
  SCREENS.loc = {
    r: null, mode: null, msg: null,       // mode: {put: 货位} 或 {move: 物品}
    show(arg) {
      this.r = null; this.mode = null; this.msg = null;
      if (!INV) { view().innerHTML = lastMsg("bad", T("k.noinv")); return; }
      this.render();
      if (arg) this.scan(arg);
    },
    refresh() { if (this.r) this.load(this.r.code, false).catch(() => {}); },
    async load(code, beep = true) {
      const r = await api(`/api/mobile/resolve?prefer=location&code=${encodeURIComponent(code)}`);
      if (beep) { if (r.type === "unknown") SCAN.bad(); else if (r.type === "order") SCAN.warn(); else SCAN.ok(); }
      this.r = r;
      this.render();
      return r;
    },
    modeBar() {
      if (!this.mode) return "";
      const t = this.mode.put ? T("l.mode_put", { l: this.mode.put }) : T("l.mode_move", { name: this.mode.move.code });
      return `<div class="mode row between"><span data-notr>${esc(t)}</span><button id="l-stop">${T("l.stop")}</button></div>`;
    },
    render() {
      const r = this.r;
      let body = "";
      if (!r) body = `<p class="hint"><span class="big-ic">🗄</span>${T("l.scan")}</p>`;
      else if (r.type === "location") {
        const l = r.location;
        body = `<div class="card"><div class="loc" data-notr>${esc(l.code)}</div><div class="small muted">${esc(TH() ? l.human_th : l.human_zh)}</div></div>
          <div class="card">${r.items.length ? `<ul class="list">${r.items.map((x) => `<li class="tap" data-code="${esc(x.code)}"><div class="grow"><div class="mono" data-notr><b>${esc(x.code)}</b></div>
            <div class="small" data-notr>${esc(nm(x.name_zh, x.name_th))}</div></div><b>${esc(+(+x.qty).toFixed(3))}</b> <span class="small" data-notr>${esc(x.unit || "")}</span></li>`).join("")}</ul>`
            : `<p class="muted">${T("l.empty")}</p>`}</div>
          ${PERMS["inv.in"] !== false ? `<button class="big primary" id="l-put">${T("l.putin")}</button>` : ""}`;
      } else if (r.type === "shelf" || r.type === "zone") {
        body = `<div class="card"><div class="loc" data-notr>${esc(T("l.shelf", { c: r.code }))}</div></div><div class="card"><ul class="list">${r.items.map((x) => `<li class="tap" data-code="${esc(x.code)}">
          <span class="loc" style="font-size:15px" data-notr>${esc(x.location || "")}</span><div class="grow"><div class="mono small" data-notr>${esc(x.code)}</div><div class="small" data-notr>${esc(nm(x.name_zh, x.name_th))}</div></div>
          <b>${esc(+(+x.qty).toFixed(3))}</b></li>`).join("") || `<li class="muted">${T("l.empty")}</li>`}</ul></div>`;
      } else if (r.type === "item") {
        const it = r.item;
        body = `<div class="card"><div class="item">${img(it.img)}<div class="grow"><div class="mono" data-notr><b>${esc(it.code)}</b></div><div class="nm" data-notr>${esc(nm(it.name_zh, it.name_th))}</div></div>
            <div class="q">${esc(+(+it.qty).toFixed(3))}</div></div>
          <p>${T("l.where")}：${it.loc ? `<b class="loc" data-notr>${esc(it.loc.code)}</b><br><span class="small muted">${esc(TH() ? it.loc.human_th : it.loc.human_zh)}</span>` : `<span class="muted">${T("k.noloc")}</span>`}</p></div>
          ${PERMS["inv.in"] !== false ? `<div class="col"><button class="big primary" id="l-move">${T("l.move")}</button>${it.loc ? `<button class="big danger" id="l-off">${T("l.takeoff")}</button>` : ""}</div>` : ""}`;
      } else if (r.type === "sku") body = `<div class="card"><b class="mono" data-notr>${esc(r.code)}</b><p class="warn">${T("l.nofile")}</p></div>`;
      else if (r.type === "order") body = `<div class="card"><p>🧾 <b class="mono" data-notr>${esc(r.order.order_no)}</b></p><button class="big primary" id="l-order">${T("go.order")}</button></div>`;
      else body = lastMsg("bad", T("unknown", { c: r.code }));
      view().innerHTML = this.modeBar() + (this.msg ? lastMsg(this.msg[0], this.msg[1]) : "") + body;
      const st = $("#l-stop"); if (st) st.addEventListener("click", () => { this.mode = null; this.msg = null; this.render(); });
      const put = $("#l-put"); if (put) put.addEventListener("click", () => { this.mode = { put: r.location.code }; this.msg = null; this.render(); });
      const mv = $("#l-move"); if (mv) mv.addEventListener("click", () => { this.mode = { move: r.item }; this.msg = null; this.render(); });
      const off = $("#l-off"); if (off) off.addEventListener("click", async () => {
        if (!(await confirmBox(T("l.takeoff_q", { c: r.item.code })))) return;
        try { await api("/api/inv/locations/assign", { json: { item_id: r.item.id, code: "" } }); SCAN.ok(); await this.load(r.item.code, false); } catch (e) { SCAN.bad(); toast(e.message, true); }
      });
      const od = $("#l-order"); if (od) od.addEventListener("click", () => go("order", r.order.order_no));
      view().querySelectorAll("[data-code]").forEach((li) => li.addEventListener("click", () => this.load(li.dataset.code, false).catch((e) => toast(e.message, true))));
    },
    async assign(item, code) {
      const r = await send("/api/inv/locations/assign", { item_id: item.id, code }, `${T("t.loc")}: ${item.code} → ${code}`);
      SCAN.ok();
      this.msg = r.queued ? ["warn", T("offline.q")] : ["ok", T("l.put_ok", { c: item.code, l: code })];
    },
    async scan(code) {
      try {
        if (this.mode) {
          const r = await api(`/api/mobile/resolve?prefer=location&code=${encodeURIComponent(code)}`);
          if (this.mode.put) {
            if (r.type === "item") { await this.assign(r.item, this.mode.put); await this.load(this.mode.put, false); return; }
            if (r.type === "location") { SCAN.ok(); this.mode = { put: r.location.code }; this.r = r; this.msg = null; this.render(); return; }
            if (r.type === "sku") { SCAN.bad(); this.msg = ["bad", `${code}：${T("l.nofile")}`]; this.render(); return; }
          } else if (this.mode.move) {
            if (r.type === "location") { const it = this.mode.move; this.mode = null; await this.assign(it, r.location.code); await this.load(it.code, false); return; }
            if (r.type === "item") { SCAN.ok(); this.mode = { move: r.item }; this.r = r; this.msg = null; this.render(); return; }
          }
          SCAN.bad(); this.msg = ["bad", T("unknown", { c: code })]; this.render(); return;
        }
        this.msg = null;
        await this.load(code);
      } catch (e) { SCAN.bad(); this.msg = ["bad", e.message]; this.render(); }
    },
  };

  // ---------------- 采购到货（v2.51）：扫采购单 / 物流单号 / 物品码 → 点数 → 记差异 → 放货位 → 入库 ----------------
  // 打开一张采购单后，再扫这张单里的物品条码 = 这一行 +1（第一次扫从 1 开始数），适合一件一件点数。
  SCREENS.rcv = {
    po: null, msg: null, open: {}, counted: {},
    async show(arg) {
      this.po = null; this.msg = null;
      if (!PUR) { view().innerHTML = lastMsg("bad", T("r.nopur")); return; }
      if (arg) { await this.scan(arg); return; }
      await this.list();
    },
    refresh() { if (this.po) this.load(this.po.id); else this.list(); },
    async list() {
      view().innerHTML = `<p class="hint"><span class="big-ic">📥</span>${T("r.scan")}</p>${this.msg ? lastMsg(this.msg[0], this.msg[1]) : ""}<div id="r-list"></div>`;
      try {
        const r = await api("/api/inv/pur/transit");
        $("#r-list").innerHTML = `<div class="card"><b>${T("r.transit")}</b>${r.pos.length ? `<ul class="list">${r.pos.map((p) => `<li class="tap" data-po="${p.id}">
          <div class="grow"><div class="mono" data-notr><b>${esc(p.no)}</b></div><div class="small muted" data-notr>${esc(p.supplier || "")}${p.tracking ? " · " + esc(p.tracking) : ""}</div></div>
          <span class="small">${this.eta(p)}</span></li>`).join("")}</ul>` : `<p class="muted">${T("r.none")}</p>`}</div>`;
        view().querySelectorAll("[data-po]").forEach((li) => li.addEventListener("click", () => this.load(+li.dataset.po).catch((e) => toast(e.message, true))));
      } catch (e) { toast(e.message, true); }
    },
    eta(p) {
      if (!p.expected_date) return "";
      const d = Math.round((new Date(p.expected_date + "T00:00:00") - new Date(new Date().toDateString())) / 86400000);
      return d < 0 ? `<b class="bad">${T("r.late", { n: -d })}</b>` : d === 0 ? `<b>${T("r.today")}</b>` : T("r.days", { n: d });
    },
    async load(id, beep) {
      const r = await api(`/api/inv/po/${id}`);
      if (!["ordered", "partial"].includes(r.po.status)) { SCAN.warn(); this.msg = ["warn", T("r.notopen", { st: srv(r.po.status_zh) })]; this.po = null; return this.list(); }
      if (beep) SCAN.ok();
      this.po = r.po; this.open = {}; this.counted = {};
      this.render();
    },
    left(l) { return Math.max(0, (l.qty || 0) - (l.received || 0)); },
    render() {
      const p = this.po;
      const lines = p.lines.filter((l) => this.left(l) > 1e-9);
      view().innerHTML = `${this.msg ? lastMsg(this.msg[0], this.msg[1]) : ""}
        <div class="card"><div class="row between"><span class="mono" style="font-size:20px;font-weight:800" data-notr>${esc(p.no)}</span><span class="small">${this.eta(p)}</span></div>
          <div class="small muted" data-notr>${esc((p.supplier || {}).name || "")}${p.tracking ? " · " + esc(p.carrier || "") + " " + esc(p.tracking) : ""}</div>
          <button class="sm" id="r-zero" style="margin-top:8px">${T("r.zero")}</button></div>
        ${lines.map((l) => { const roll = !!l.rolls, left = roll ? this.left(l) / (l.net_g || 1000) : this.left(l), c = this.counted[l.id];
          return `<div class="card" data-rl="${l.id}"><div class="nm" data-notr><b>${esc(nm(l.name_zh, l.name_th))}</b></div>
            <div class="small muted"><span data-notr>${esc(l.code)}</span> · ${T("r.left")} <b>${+left.toFixed(3)}</b> ${roll ? T("r.roll") : `<span data-notr>${esc(l.unit || "")}</span>`}</div>
            <div class="small muted" style="margin-top:8px">${T("r.got")}</div>
            <div class="step"><button data-m="-">−</button><input type="number" inputmode="decimal" data-r="qty" value="${c != null ? c : +left.toFixed(3)}"><button data-m="+">+</button></div>
            <input data-r="loc" placeholder="${esc(T("r.loc"))}" value="${esc(l.location || "")}" style="margin-top:8px" data-notr>
            <button class="sm" data-iss style="margin-top:8px">${T("r.issue")}</button>
            <div class="col ${this.open[l.id] ? "" : "hidden"}" data-issbox style="margin-top:6px"><select data-r="kind">${["short", "damaged", "wrong", "extra"].map((k) => `<option value="${k}">${T("r.k." + k)}</option>`).join("")}</select>
              <input type="number" inputmode="decimal" data-r="iq" placeholder="${esc(T("r.iq"))}"><input data-r="note" placeholder="${esc(T("r.inote"))}" data-notr></div></div>`; }).join("")}
        <button class="big primary" id="r-ok">${T("r.ok")}</button>`;
      view().querySelectorAll("[data-rl]").forEach((box) => {
        const id = +box.dataset.rl, q = box.querySelector('[data-r="qty"]');
        box.querySelectorAll("[data-m]").forEach((b) => b.addEventListener("click", () => { q.value = Math.max(0, (+q.value || 0) + (b.dataset.m === "+" ? 1 : -1)); this.counted[id] = +q.value; }));
        q.addEventListener("input", () => { this.counted[id] = q.value; });
        box.querySelector("[data-iss]").addEventListener("click", () => { this.open[id] = !this.open[id]; box.querySelector("[data-issbox]").classList.toggle("hidden", !this.open[id]); });
      });
      $("#r-zero").addEventListener("click", () => { view().querySelectorAll('[data-r="qty"]').forEach((x) => { x.value = 0; this.counted[+x.closest("[data-rl]").dataset.rl] = 0; }); });
      $("#r-ok").addEventListener("click", (e) => this.submit(e.target));
    },
    async submit(btn) {
      if (PERMS["inv.in"] === false) { SCAN.bad(); toast(T("r.noperm"), true); return; }
      const p = this.po, qtys = {}, issues = [], locations = {};
      view().querySelectorAll("[data-rl]").forEach((box) => {
        const id = box.dataset.rl, l = p.lines.find((x) => String(x.id) === id), g = (k) => box.querySelector(`[data-r="${k}"]`).value.trim();
        if (+g("qty") > 0) qtys[id] = g("qty");
        if (this.open[+id] && (+g("iq") > 0 || g("note"))) issues.push({ line_id: +id, kind: g("kind"), qty: g("iq") || 0, note: g("note") });
        if (g("loc") && g("loc").toUpperCase() !== String(l.location || "").toUpperCase()) locations[l.item_id] = g("loc");
      });
      btn.disabled = true;
      try {
        const r = await send("/api/inv/pur/receive", { po_id: p.id, qtys, issues, locations }, `${T("t.rcv")} ${p.no}`);
        SCAN.ok();
        if (r.queued) { this.msg = ["warn", T("offline.q")]; this.po = null; return this.list(); }
        (r.warnings || []).forEach((w) => toast(srv(w), true));
        const ls = Object.entries(qtys).map(([k, v]) => `${k}:${Math.ceil(+v)}`).join(",");
        view().innerHTML = `${lastMsg("ok", T("r.done", { no: p.no }))}<div class="col">
          ${ls ? `<a class="btn big" href="/print/pur-labels?po=${encodeURIComponent(p.no)}&lines=${ls}${TH() ? "&lang=th" : ""}" target="_blank">${T("r.print")}</a>` : ""}
          <button class="big primary" id="r-next">${T("r.next")}</button></div>`;
        this.po = null; this.msg = null;
        $("#r-next").addEventListener("click", () => this.list());
      } catch (e) { SCAN.bad(); this.msg = ["bad", e.message]; btn.disabled = false; this.render(); }
    },
    async scan(code) {
      try {
        if (this.po) {
          const k = code.trim().toUpperCase();
          const l = this.po.lines.find((x) => String(x.code || "").toUpperCase() === k && this.left(x) > 1e-9);
          if (l) {
            const box = view().querySelector(`[data-rl="${l.id}"]`), q = box.querySelector('[data-r="qty"]');
            this.byScan = this.byScan || {};
            const n = this.byScan[l.id] ? (+q.value || 0) + 1 : 1;
            this.byScan[l.id] = true;
            q.value = n; this.counted[l.id] = n; SCAN.ok(); toast(T("r.plus", { c: l.code }));
            box.scrollIntoView({ block: "center", behavior: "smooth" });
            return;
          }
        }
        const r = await api(`/api/inv/pur/scan?code=${encodeURIComponent(code)}`);
        this.msg = null;
        if (r.type === "po") { this.byScan = {}; return this.load(r.po.id, true); }
        if (r.type === "item") {
          if (r.pos.length === 1) { this.byScan = {}; await this.load(r.pos[0].id, true); return this.scan(code); }
          if (!r.pos.length) { SCAN.bad(); this.msg = ["bad", T("r.noitem_po", { c: code })]; return this.po ? this.render() : this.list(); }
          SCAN.warn();
          const s = sheet(`<h3>${T("r.pick")}</h3><ul class="list">${r.pos.map((p) => `<li class="tap" data-po="${p.id}"><b class="mono grow" data-notr>${esc(p.no)}</b><span class="small" data-notr>${esc(p.supplier || "")}</span></li>`).join("")}</ul>`);
          s.querySelectorAll("[data-po]").forEach((li) => li.addEventListener("click", async () => { closeSheet(); this.byScan = {}; await this.load(+li.dataset.po, true); this.scan(code); }));
          return;
        }
        SCAN.bad(); this.msg = ["bad", this.po ? T("r.notin", { c: code }) : T("unknown", { c: code })];
        return this.po ? this.render() : this.list();
      } catch (e) { SCAN.bad(); toast(e.message, true); }
    },
  };


  // ---------------- 启动 ----------------
  document.documentElement.lang = TH() ? "th" : "zh";
  if (SCAN.isApp()) {
    document.body.classList.add("in-app");
    $("#app-set").classList.remove("hidden");
    $("#app-set").addEventListener("click", () => { try { window.Android3D.openSettings(); } catch { /* 老版本 App */ } });
  }
  boot();
})();
