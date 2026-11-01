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
    "t.count": ["盘点", "ตรวจนับ"], "t.count.s": ["一个货位一个货位数", "นับทีละตำแหน่ง"],
    "t.loc": ["货位", "ตำแหน่งจัดเก็บ"], "t.loc.s": ["货位里有什么、东西在哪", "ในช่องมีอะไร ของอยู่ไหน"],
    "t.put": ["上架", "จัดเก็บเข้าช่อง"], "t.put.s": ["扫商品，按推荐扫货位放好", "สแกนสินค้า แล้วสแกนช่องที่แนะนำ"],
    "t.move": ["移库", "ย้ายตำแหน่ง"], "t.move.s": ["扫原货位 → 商品 → 新货位；补货任务", "สแกนช่องเดิม → สินค้า → ช่องใหม่ งานเติมสินค้า"],
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
    "c.scan": ["扫货位 / 货架 / 库区条码，开始按货位盘点", "สแกนโค้ดตำแหน่ง / ชั้นวาง / โซน เพื่อเริ่มตรวจนับตามตำแหน่ง"],
    "c.open": ["没盘完的盘点单（点一下接着盘）", "ใบตรวจนับที่ยังไม่เสร็จ (แตะเพื่อทำต่อ)"], "c.prog": ["货位数完 {d} / {t}", "นับช่องแล้ว {d} / {t}"],
    "c.diffs": ["{n} 个差异", "ต่าง {n} รายการ"], "c.now": ["正在数", "กำลังนับ"],
    "c.how": ["扫商品一下 +1，或者直接填数；没有的填 0。数完点下面的按钮，再扫下一个货位。", "สแกนสินค้าครั้งละ +1 หรือกรอกจำนวน ไม่มีให้ใส่ 0 นับเสร็จกดปุ่มด้านล่าง แล้วสแกนช่องถัดไป"],
    "c.extra": ["账上不在这里", "ในระบบไม่อยู่ที่นี่"], "c.locdone": ["✅ 这个货位数完了", "✅ ช่องนี้นับเสร็จแล้ว"],
    "c.alldone": ["货位都数完了：让老板确认盘点", "นับครบทุกช่องแล้ว: ให้เจ้าของยืนยัน"], "c.locs": ["货位（点一下换着数）", "ตำแหน่ง (แตะเพื่อเปลี่ยน)"],
    "c.boss": ["数完让老板确认", "นับเสร็จแล้วให้เจ้าของยืนยัน"], "c.locsaved": ["✔ {l} 已保存", "✔ บันทึก {l} แล้ว"],
    "c.confirm_left": ["还有 {n} 个货位没数（没数的不调整），确认盘点？", "ยังมี {n} ช่องที่ยังไม่นับ (ไม่ปรับ) ยืนยันไหม?"],
    "c.notarea": ["{l} 不在这张盘点单里（换一张：点「换个货位盘点」）", "{l} ไม่อยู่ในใบนี้ (เปลี่ยนใบ: กด「ตรวจตำแหน่งอื่น」)"],
    "c.area": ["盘点范围", "ขอบเขตตรวจนับ"], "c.book": ["账面", "ในระบบ"], "c.counted": ["实盘", "นับได้"],
    "c.save": ["💾 保存", "💾 บันทึก"], "c.confirm": ["✅ 确认盘点（改库存）", "✅ ยืนยันตรวจนับ (แก้สต็อก)"], "c.zero": ["没扫到的算 0", "ที่ไม่ได้สแกนนับเป็น 0"],
    "c.notin": ["{c} 不在这里的账上{w}", "{c} ไม่อยู่ในรายการที่นี่{w}"], "c.at": ["（账上在 {l}）", " (ในระบบอยู่ที่ {l})"],
    "c.saved": ["已保存", "บันทึกแล้ว"], "c.confirmed": ["盘点完成，{n} 个有差异已调整", "ตรวจนับเสร็จ ปรับ {n} รายการที่ต่าง"],
    "c.confirm_q": ["确认盘点？填了数的按实盘数改库存", "ยืนยันตรวจนับ? รายการที่กรอกจะแก้สต็อกตามจำนวนจริง"],
    "c.new": ["换个货位盘点", "ตรวจตำแหน่งอื่น"], "c.diff": ["差", "ต่าง"], "c.needitem": ["这是商品码：先扫货位开始盘点", "นี่คือโค้ดสินค้า: สแกนตำแหน่งก่อน"],
    // 货位
    "l.scan": ["扫货位看里面有什么；扫商品看它在哪", "สแกนตำแหน่งดูว่ามีอะไร สแกนสินค้าดูว่าอยู่ไหน"],
    "l.empty": ["这个货位是空的", "ตำแหน่งนี้ว่าง"], "l.putin": ["📥 把待上架的东西放到这里", "📥 วางของที่รอจัดเก็บที่นี่"],
    "l.cap": ["容量", "ความจุ"], "l.mvfrom": ["↔ 从这里移走", "↔ ย้ายออกจากที่นี่"], "l.goput": ["📥 上架", "📥 จัดเก็บ"], "l.gomove": ["↔ 移库", "↔ ย้ายตำแหน่ง"], "l.move": ["↔ 放到 / 换到别的货位", "↔ วาง / ย้ายไปตำแหน่งอื่น"],
    "l.takeoff": ["拿下来（不放货位）", "เอาออก (ไม่มีตำแหน่ง)"],
    "l.mode_put": ["放到 {l}：扫要放进来的商品", "วางที่ {l}: สแกนสินค้าที่จะวาง"], "l.mode_move": ["{name}：扫新的货位", "{name}: สแกนตำแหน่งใหม่"],
    "l.stop": ["结束", "เสร็จ"], "l.put_ok": ["✔ {c} → {l}", "✔ {c} → {l}"], "l.where": ["放在这些货位（★ = 主货位，拣货先拿这里）", "อยู่ในช่องเหล่านี้ (★ = ช่องหลัก หยิบที่นี่ก่อน)"], "l.shelf": ["货架 {c}", "ชั้นวาง {c}"],
    "l.nofile": ["还没有库存档，先在「库存」里入库", "ยังไม่มีในสต็อก ให้รับเข้าที่「สต็อก」ก่อน"],
    "l.takeoff_q": ["把 {c} 从货位拿下来？", "เอา {c} ออกจากตำแหน่ง?"],
    // 上架 / 移库（v2.52）
    "pk.go": ["去 {l} 拿", "ไปหยิบที่ {l}"],
    "u.pending": ["待上架", "รอจัดเก็บ"], "u.sug": ["推荐货位", "ตำแหน่งที่แนะนำ"], "u.r.same": ["同物品已在", "สินค้าเดิมอยู่"], "u.r.near": ["同类附近空位", "ช่องว่างใกล้หมวดเดียวกัน"],
    "u.r.empty": ["空货位", "ช่องว่าง"], "u.nosug": ["没有合适的空位：扫一个货位也能放", "ไม่มีช่องที่เหมาะ: สแกนช่องไหนก็วางได้"], "u.qty": ["放多少", "จำนวนที่วาง"],
    "u.scanloc": ["👉 扫货位条码确认放好", "👉 สแกนป้ายตำแหน่งเพื่อยืนยัน"], "u.back": ["返回列表", "กลับไปรายการ"],
    "u.scan": ["扫要上架的商品（或者点下面的）", "สแกนสินค้าที่จะจัดเก็บ (หรือแตะด้านล่าง)"], "u.scanat": ["放到 {l}：扫商品", "วางที่ {l}: สแกนสินค้า"],
    // v2.53：料卷、质检、退货
    "t.spool": ["料卷", "ม้วนฟิลาเมนต์"], "t.spool.s": ["扫料卷 → 扫货位 / 打印机槽：上架、上机、下机、称重", "สแกนม้วน → สแกนตำแหน่ง / ช่องเครื่องพิมพ์: จัดเก็บ ใส่ ถอด ชั่ง"],
    "t.qc": ["质检", "ตรวจคุณภาพ"], "t.qc.s": ["待检区的成品：合格扫货位上架，不合格放次品区", "สินค้าในโซนรอตรวจ: ผ่านสแกนตำแหน่งจัดเก็บ ไม่ผ่านไปโซนชำรุด"],
    "t.ret": ["退货", "สินค้าคืน"], "t.ret.s": ["退回的货：重新上架或放次品区；扫商品登记退货", "ของที่ถูกส่งคืน: จัดเก็บใหม่หรือโซนชำรุด สแกนสินค้าเพื่อบันทึก"],
    "s.scan": ["扫料卷标签（F0001）", "สแกนป้ายม้วน (F0001)"], "s.then": ["👉 扫货位放好；扫打印机 · 槽 = 上机", "👉 สแกนตำแหน่งเพื่อวาง; สแกนเครื่องพิมพ์ · ช่อง = ใส่เครื่อง"],
    "s.where": ["现在在", "ตอนนี้อยู่ที่"], "s.none": ["待上架", "รอจัดเก็บ"], "s.left": ["剩余", "เหลือ"], "s.unload": ["下机（放回待上架）", "ถอดออก (รอจัดเก็บ)"],
    "s.empty": ["用完了", "ใช้หมดแล้ว"], "s.gross": ["称重盘点：整卷多少克（含空料盘）", "ชั่งตรวจนับ: ทั้งม้วนกี่กรัม (รวมแกนเปล่า)"], "s.weigh": ["⚖ 记下重量", "⚖ บันทึกน้ำหนัก"],
    "s.ok": ["✔ {c} → {l}", "✔ {c} → {l}"], "s.wok": ["✔ {c} 剩 {g} g（{d} g）", "✔ {c} เหลือ {g} g ({d} g)"], "s.emptyq": ["{c} 用完了？剩下的会从库存扣掉", "{c} ใช้หมดแล้ว? ที่เหลือจะตัดจากสต็อก"],
    "q.list": ["待检区", "โซนรอตรวจ"], "q.none": ["没有等质检的成品 ✓", "ไม่มีสินค้ารอตรวจ ✓"], "q.pass": ["👉 合格：扫货位上架（或点推荐）", "👉 ผ่าน: สแกนตำแหน่งจัดเก็บ (หรือกดที่แนะนำ)"],
    "q.fail": ["不合格 → 次品区", "ไม่ผ่าน → โซนชำรุด"], "q.scrap": ["直接报废", "ทิ้งเลย"], "q.sug": ["放到推荐的 {l}", "วางที่แนะนำ {l}"],
    "r.list": ["退货区", "โซนสินค้าคืน"], "r.def": ["次品区", "โซนชำรุด"], "r.none": ["退货区是空的 ✓", "โซนสินค้าคืนว่าง ✓"], "r.restock": ["👉 没问题：扫货位重新上架（或点推荐）", "👉 ไม่มีปัญหา: สแกนตำแหน่งจัดเก็บใหม่ (หรือกดที่แนะนำ)"],
    "r.todef": ["有问题 → 次品区", "มีปัญหา → โซนชำรุด"], "r.newq": ["登记退货 {c}：几个？", "บันทึกสินค้าคืน {c}: กี่ชิ้น?"], "r.added": ["✔ {c} ×{n} 放进退货区", "✔ {c} ×{n} เข้าโซนสินค้าคืน"],
    "u.list": ["待上架", "รอจัดเก็บ"], "u.none": ["没有待上架的东西 ✓", "ไม่มีของรอจัดเก็บ ✓"], "u.force": ["还是要放进去吗？", "ยังจะวางไหม?"],
    "u.notpending": ["{c} 没有待上架的数量（要换位置用「移库」）", "{c} ไม่มีจำนวนรอจัดเก็บ (ย้ายใช้「ย้ายตำแหน่ง」)"],
    "m.s1": ["扫原货位", "สแกนช่องเดิม"], "m.s2": ["扫要搬的商品（一下 +1）或者填数", "สแกนสินค้าที่จะย้าย (ครั้งละ +1) หรือกรอกจำนวน"], "m.s3": ["扫新货位", "สแกนช่องใหม่"],
    "m.reset": ["重来", "เริ่มใหม่"], "m.have": ["有", "มี"], "m.all": ["全部", "ทั้งหมด"], "m.tasks": ["补货任务（点一下照着搬）", "งานเติมสินค้า (แตะแล้วย้ายตาม)"],
    "m.repl": ["补货", "เติม"], "m.dotask": ["搬好后扫 {l}", "ย้ายเสร็จแล้วสแกน {l}"], "m.ok": ["✔ {f} → {t}（{n} 样）", "✔ {f} → {t} ({n} รายการ)"],
    "m.notfrom": ["{c} 不在 {l}", "{c} ไม่อยู่ที่ {l}"],
    // 采购到货（v2.51）
    "r.scan": ["扫采购单号 / 物流单号 / 物品条码", "สแกนเลขใบสั่งซื้อ / เลขพัสดุ / บาร์โค้ดสินค้า"], "r.transit": ["在途的采购单", "ใบสั่งซื้อที่กำลังส่ง"],
    "r.none": ["没有在途的采购单", "ไม่มีใบสั่งซื้อที่กำลังส่ง"], "r.late": ["晚了 {n} 天", "ช้า {n} วัน"], "r.today": ["今天到", "ถึงวันนี้"],
    "r.days": ["还有 {n} 天", "อีก {n} วัน"], "r.left": ["还没到", "ยังไม่ถึง"], "r.got": ["这次到了", "ถึงรอบนี้"], "r.roll": ["卷", "ม้วน"],
    "r.issue": ["⚠ 有问题（少发 / 破损）", "⚠ มีปัญหา (ขาด / เสีย)"], "r.k.short": ["少发", "ส่งขาด"], "r.k.damaged": ["破损", "เสียหาย"],
    "r.k.wrong": ["发错", "ส่งผิด"], "r.k.extra": ["多发", "ส่งเกิน"], "r.iq": ["数量", "จำนวน"], "r.inote": ["说明", "หมายเหตุ"],
    "r.loc": ["放到货位（可空）", "วางตำแหน่ง (เว้นได้)"], "r.sug": ["推荐货位 {l}（空 = 按推荐放）", "แนะนำ {l} (เว้นว่าง = วางตามแนะนำ)"], "r.ok": ["✅ 确认入库", "✅ ยืนยันรับเข้า"], "r.done": ["已入库：{no}", "รับเข้าแล้ว: {no}"],
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
      const tiles = [["order", "🔎"], ["ship", "🚚"], ["pack", "✅"], ...(INV ? [["stock", "📦"], ["loc", "🗄"], ["put", "📍"], ["move", "🔀"], ["count", "🧮"], ["spool", "🧵"], ["qc", "🔍"], ["ret", "↩"]] : []), ...(PUR ? [["rcv", "📥"]] : [])];
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
          ${i.loc ? `<div class="small" data-notr>📍 ${esc(T("pk.go", { l: i.loc }))}</div>` : ""}
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

  // ---------------- 盘点（v2.52：按货位，一个货位一个货位数）----------------
  // 扫货位 / 货架 / 库区 → 开一张盘点单（或者接着上次的）；扫货位 = 开始数这个货位；扫商品 = +1；「这个货位数完了」→ 下一个。
  const qn = (v) => +(+v || 0).toFixed(3);
  SCREENS.count = {
    doc: null, cur: null, cnt: {}, msg: null,
    async show() {
      this.msg = null; this.cur = null;
      if (!INV) { view().innerHTML = lastMsg("bad", T("k.noinv")); return; }
      const did = +(localStorage.getItem("m3d_count_doc") || 0);
      this.doc = null;
      if (did) {
        try { const r = await api(`/api/inv/stocktake/${did}`); if (r.doc && r.doc.status === "draft" && r.doc.by_location) this.doc = r.doc; } catch { /* 没了 */ }
        if (!this.doc) localStorage.removeItem("m3d_count_doc");
      }
      if (this.doc) this.pickNext();
      this.render();
    },
    refresh() { if (this.doc) this.reload().then(() => this.render()).catch(() => {}); },
    async reload() { const r = await api(`/api/inv/stocktake/${this.doc.id}`); this.doc = r.doc; },
    pickNext() {
      const nx = this.doc.locs.find((l) => !l.done);
      this.setCur(nx ? nx.code : null);
    },
    setCur(code) {
      this.cur = code;
      this.cnt = {};
      if (!code) return;
      try { this.cnt = JSON.parse(localStorage.getItem(`m3d_cnt_${this.doc.id}_${code}`) || "{}"); } catch { this.cnt = {}; }
      const l = this.loc();
      if (l && l.done && !Object.keys(this.cnt).length) l.rows.forEach((x) => { if (x.counted != null) this.cnt[x.code] = { id: x.item_id, q: x.counted, nm: [x.name_zh, x.name_th] }; });
    },
    keep() { try { localStorage.setItem(`m3d_cnt_${this.doc.id}_${this.cur}`, JSON.stringify(this.cnt)); } catch { /* 忽略 */ } },
    loc() { return this.doc && this.doc.locs.find((l) => l.code === this.cur); },
    async listOpen() {
      try {
        const r = await api("/api/inv/docs?kind=stocktake");
        return r.docs.filter((d) => d.status === "draft" && (d.ref || "").startsWith("area:"));
      } catch { return []; }
    },
    async render() {
      const d = this.doc;
      const msg = this.msg ? lastMsg(this.msg[0], this.msg[1]) : "";
      if (!d) {
        view().innerHTML = `${msg}<p class="hint"><span class="big-ic">🧮</span>${T("c.scan")}</p><div id="c-open"></div>`;
        const open = await this.listOpen();
        const box = $("#c-open");
        if (box && open.length) {
          box.innerHTML = `<div class="card"><b>${T("c.open")}</b><ul class="list">${open.map((x) => `<li class="tap" data-doc="${x.id}"><b class="mono grow" data-notr>${esc(x.ref.slice(5))}</b><span class="small muted mono" data-notr>${esc(x.no)}</span></li>`).join("")}</ul></div>`;
          box.querySelectorAll("[data-doc]").forEach((li) => li.addEventListener("click", async () => {
            try { const r = await api(`/api/inv/stocktake/${li.dataset.doc}`); this.doc = r.doc; localStorage.setItem("m3d_count_doc", r.doc.id); this.pickNext(); this.render(); } catch (e) { toast(e.message, true); }
          }));
        }
        return;
      }
      const p = d.progress, l = this.loc();
      const rows = l ? l.rows : [];
      const shown = {};
      rows.forEach((x) => { shown[x.code] = { id: x.item_id, nm: [x.name_zh, x.name_th], unit: x.unit, book: x.book }; });
      Object.entries(this.cnt).forEach(([c, v]) => { if (!shown[c]) shown[c] = { id: v.id, nm: v.nm || ["", ""], extra: true }; });
      view().innerHTML = `${msg}
        <div class="card"><div class="row between"><span>${T("c.area")}：<b class="loc" data-notr style="font-size:18px">${esc(areaOf(d))}</b></span><span class="small muted mono" data-notr>${esc(d.no)}</span></div>
          <div class="pbar"><i style="width:${p.total ? Math.round(100 * p.done / p.total) : 0}%"></i></div>
          <div class="small">${T("c.prog", { d: p.done, t: p.total })}${p.diffs ? ` · <b class="bad">${T("c.diffs", { n: p.diffs })}</b>` : ""}</div></div>
        ${l ? `<div class="card"><div class="row between"><div><div class="small muted">${T("c.now")}</div><div class="loc" data-notr>${esc(l.code)}</div></div>${l.done ? `<span class="ok">✓</span>` : ""}</div>
            <p class="small muted">${T("c.how")}</p>
            <ul class="list">${Object.entries(shown).map(([c, x]) => { const v = this.cnt[c]; return `<li><div class="grow"><div class="mono" data-notr><b>${esc(c)}</b>${x.extra ? ` <span class="warn small">${T("c.extra")}</span>` : ""}</div>
              <div class="small" data-notr>${esc(nm(x.nm[0], x.nm[1]))}</div>${x.book != null ? `<div class="small muted">${T("c.book")} ${esc(qn(x.book))}</div>` : ""}</div>
              <div class="step" style="width:150px"><button class="sm" data-dec="${esc(c)}">−</button><input type="number" inputmode="decimal" data-cnt="${esc(c)}" value="${v ? esc(v.q) : ""}" placeholder="—" style="min-height:40px;font-size:18px;padding:4px"><button class="sm" data-inc="${esc(c)}">+</button></div></li>`; }).join("") || `<li class="muted">${T("l.empty")}</li>`}</ul>
            <button class="big okb" id="c-done">${T("c.locdone")}</button></div>`
          : `<div class="card"><p>${T("c.alldone")}</p></div>`}
        <div class="card"><b class="small">${T("c.locs")}</b><div class="chipsm">${d.locs.map((x) => `<button class="sm ${x.done ? "okc" : ""} ${x.code === this.cur ? "on" : ""}" data-go="${esc(x.code)}" data-notr>${esc(x.code)}${x.done ? " ✓" : ""}${x.diffs ? " ⚠" : ""}</button>`).join("")}</div></div>
        <div class="col">${PERMS["inv.adjust"] !== false ? `<button class="big primary" id="c-confirm">${T("c.confirm")}</button>` : `<p class="small muted">${T("c.boss")}</p>`}
          <button class="big" id="c-new">${T("c.new")}</button></div>`;
      const set = (c, q) => { const x = shown[c]; this.cnt[c] = { id: x.id, q: Math.max(0, qn(q)), nm: x.nm }; this.keep(); };
      view().querySelectorAll("[data-inc]").forEach((b) => b.addEventListener("click", () => { const c = b.dataset.inc; set(c, ((this.cnt[c] || {}).q || 0) + 1); this.render(); }));
      view().querySelectorAll("[data-dec]").forEach((b) => b.addEventListener("click", () => { const c = b.dataset.dec; set(c, ((this.cnt[c] || {}).q || 0) - 1); this.render(); }));
      view().querySelectorAll("[data-cnt]").forEach((inp) => inp.addEventListener("change", () => { if (inp.value === "") { delete this.cnt[inp.dataset.cnt]; this.keep(); } else set(inp.dataset.cnt, inp.value); }));
      view().querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => { this.setCur(b.dataset.go); this.msg = null; this.render(); }));
      const dn = $("#c-done"); if (dn) dn.addEventListener("click", (e) => this.saveLoc(e.target));
      const cf = $("#c-confirm"); if (cf) cf.addEventListener("click", (e) => this.confirm(e.target));
      $("#c-new").addEventListener("click", () => { localStorage.removeItem("m3d_count_doc"); this.doc = null; this.cur = null; this.msg = null; this.render(); });
    },
    async saveLoc(btn) {
      btn.disabled = true;
      const counts = {};
      Object.entries(this.cnt).forEach(([c, v]) => { counts[v.id || c] = v.q; });
      try {
        const r = await api(`/api/inv/stocktake/${this.doc.id}/loc`, { json: { code: this.cur, counts, complete: true } });
        const done = this.cur;
        try { localStorage.removeItem(`m3d_cnt_${this.doc.id}_${done}`); } catch { /* 忽略 */ }
        this.doc = r.doc; SCAN.ok();
        const l = this.doc.locs.find((x) => x.code === done);
        this.msg = ["ok", T("c.locsaved", { l: done }) + (l && l.diffs ? " · " + T("c.diffs", { n: l.diffs }) : "")];
        this.pickNext();
      } catch (e) { SCAN.bad(); this.msg = ["bad", srv(e.message)]; }
      this.render();
    },
    async confirm(btn) {
      const left = this.doc.progress.total - this.doc.progress.done;
      if (!(await confirmBox(left ? T("c.confirm_left", { n: left }) : T("c.confirm_q")))) return;
      btn.disabled = true;
      try {
        const r = await api(`/api/inv/stocktake/${this.doc.id}/confirm`, { json: {} });
        SCAN.ok(); localStorage.removeItem("m3d_count_doc"); this.doc = null; this.cur = null;
        this.msg = ["ok", T("c.confirmed", { n: r.doc.progress ? r.doc.progress.diffs : 0 })];
      } catch (e) { SCAN.bad(); this.msg = ["bad", srv(e.message)]; }
      this.render();
    },
    async start(code) {
      const r = await api("/api/inv/stocktake", { json: { area: code, note: "📱" } });
      this.doc = r.doc;
      localStorage.setItem("m3d_count_doc", r.doc.id);
      SCAN.ok(); this.msg = null;
      this.pickNext();
      this.render();
    },
    async scan(code) {
      const k = code.trim().toUpperCase();
      try {
        if (this.doc && this.cur) {             // 先看是不是这个货位上的商品
          const l = this.loc();
          const row = l && l.rows.find((x) => String(x.code).toUpperCase() === k);
          const had = Object.keys(this.cnt).find((c) => c.toUpperCase() === k);
          if (row || had) {
            const c = row ? row.code : had;
            const cur = this.cnt[c] || { id: row ? row.item_id : this.cnt[had].id, q: 0, nm: row ? [row.name_zh, row.name_th] : this.cnt[had].nm };
            cur.q = qn(cur.q + 1); this.cnt[c] = cur; this.keep();
            SCAN.ok(); this.msg = ["ok", `✔ ${c}  ${cur.q}`]; this.render(); return;
          }
        }
        if (this.doc) {
          const l = this.doc.locs.find((x) => x.code.toUpperCase() === k.replace(/^([A-Z]{1,2})(\d{1,2})-(\d{1,2})-(\d{1,2})$/, (m, a, b, c, d) => `${a}${+b}-${String(+c).padStart(2, "0")}-${String(+d).padStart(2, "0")}`));
          if (l) { SCAN.ok(); this.setCur(l.code); this.msg = null; this.render(); return; }
        }
        const r = await api(`/api/mobile/resolve?prefer=location&code=${encodeURIComponent(code)}`);
        if (["location", "shelf", "zone"].includes(r.type)) {
          const ac = r.type === "location" ? r.location.code : String(r.code || "").toUpperCase();
          if (this.doc) { SCAN.warn(); this.msg = ["warn", T("c.notarea", { l: ac })]; this.render(); return; }
          await this.start(ac);
          return;
        }
        if ((r.type === "item") && this.doc && this.cur) {      // 账上不在这个货位的商品：也记下（放错地方的）
          SCAN.warn();
          this.cnt[r.item.code] = { id: r.item.id, q: 1, nm: [r.item.name_zh, r.item.name_th] }; this.keep();
          this.msg = ["warn", T("c.notin", { c: r.item.code, w: r.item.loc ? T("c.at", { l: r.item.loc.code }) : "" })];
        } else if (r.type === "item") { SCAN.warn(); this.msg = ["warn", T("c.needitem")]; }
        else { SCAN.bad(); this.msg = ["bad", T("unknown", { c: code })]; }
      } catch (e) { SCAN.bad(); this.msg = ["bad", srv(e.message)]; }
      this.render();
    },
  };
  const areaOf = (d) => ((d.ref || "").startsWith("area:") ? d.ref.slice(5) : "—");
  const ZT = { pick: ["拣货区", "โซนหยิบสินค้า"], reserve: ["备货区", "โซนสต็อกสำรอง"], staging: ["暂存区", "โซนพักสินค้า"], returns: ["退货区", "โซนสินค้าคืน"],
    defect: ["次品区", "โซนสินค้าชำรุด"], supply: ["耗材区", "โซนวัสดุสิ้นเปลือง"] };
  const ztName = (t) => (ZT[t] ? ZT[t][TH() ? 1 : 0] : "");

  // ---------------- 货位（查：货位里有什么、物品在哪些货位）----------------
  SCREENS.loc = {
    r: null, msg: null,
    show(arg) {
      this.r = null; this.msg = null;
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
    render() {
      const r = this.r;
      let body = "";
      if (!r) body = `<p class="hint"><span class="big-ic">🗄</span>${T("l.scan")}</p>`;
      else if (r.type === "location") {
        const l = r.location;
        body = `<div class="card"><div class="loc" data-notr>${esc(l.code)}</div><div class="small muted">${esc(TH() ? l.human_th : l.human_zh)}</div>
            <div class="small"><span class="pill">${esc(ztName(l.ztype))}</span>${l.capacity != null ? ` · ${T("l.cap")} <b>${esc(qn(l.total))} / ${esc(qn(l.capacity))}</b>` : ""}${l.fixed ? ` · 📌 <span data-notr>${esc(l.fixed.code)}</span>` : ""}</div></div>
          <div class="card">${r.items.length ? `<ul class="list">${r.items.map((x) => `<li class="tap" data-code="${esc(x.code)}"><div class="grow"><div class="mono" data-notr><b>${esc(x.code)}</b>${x.primary ? " ★" : ""}</div>
            <div class="small" data-notr>${esc(nm(x.name_zh, x.name_th))}</div></div><b>${esc(qn(x.qty))}</b> <span class="small" data-notr>${esc(x.unit || "")}</span></li>`).join("")}</ul>`
            : `<p class="muted">${T("l.empty")}</p>`}</div>
          ${PERMS["inv.in"] !== false ? `<div class="col"><button class="big primary" id="l-put">${T("l.putin")}</button>${r.items.some((x) => x.qty > 0) ? `<button class="big" id="l-mvfrom">${T("l.mvfrom")}</button>` : ""}</div>` : ""}`;
      } else if (r.type === "shelf" || r.type === "zone") {
        body = `<div class="card"><div class="loc" data-notr>${esc(T("l.shelf", { c: r.code }))}</div></div><div class="card"><ul class="list">${r.items.map((x) => `<li class="tap" data-code="${esc(x.code)}">
          <span class="loc" style="font-size:15px" data-notr>${esc(x.location || "")}</span><div class="grow"><div class="mono small" data-notr>${esc(x.code)}</div><div class="small" data-notr>${esc(nm(x.name_zh, x.name_th))}</div></div>
          <b>${esc(qn(x.qty))}</b></li>`).join("") || `<li class="muted">${T("l.empty")}</li>`}</ul></div>`;
      } else if (r.type === "item") {
        const it = r.item, ls = (it.locs && it.locs.locations) || [], un = (it.locs && it.locs.unplaced) || 0;
        body = `<div class="card"><div class="item">${img(it.img)}<div class="grow"><div class="mono" data-notr><b>${esc(it.code)}</b></div><div class="nm" data-notr>${esc(nm(it.name_zh, it.name_th))}</div></div>
            <div class="q">${esc(qn(it.qty))}</div></div>
          <p class="small muted">${T("l.where")}</p>
          <ul class="list">${ls.map((x) => `<li class="tap" data-code="${esc(x.code)}"><span class="loc" style="font-size:18px" data-notr>${esc(x.code)}</span>${x.primary ? " ★" : ""}
            <span class="grow small muted">${esc(ztName(x.ztype))}</span><b>${esc(qn(x.qty))}</b></li>`).join("")}
            ${un > 1e-9 ? `<li><span class="warn grow">${T("u.pending")}</span><b>${esc(qn(un))}</b></li>` : ""}${!ls.length && un <= 1e-9 ? `<li class="muted">${T("k.noloc")}</li>` : ""}</ul></div>
          ${PERMS["inv.in"] !== false ? `<div class="col">${un > 1e-9 ? `<button class="big primary" id="l-goput">${T("l.goput")}</button>` : ""}${ls.length ? `<button class="big" id="l-gomove">${T("l.gomove")}</button>` : ""}</div>` : ""}`;
      } else if (r.type === "sku") body = `<div class="card"><b class="mono" data-notr>${esc(r.code)}</b><p class="warn">${T("l.nofile")}</p></div>`;
      else if (r.type === "order") body = `<div class="card"><p>🧾 <b class="mono" data-notr>${esc(r.order.order_no)}</b></p><button class="big primary" id="l-order">${T("go.order")}</button></div>`;
      else body = lastMsg("bad", T("unknown", { c: r.code }));
      view().innerHTML = (this.msg ? lastMsg(this.msg[0], this.msg[1]) : "") + body;
      const put = $("#l-put"); if (put) put.addEventListener("click", () => go("put", "@" + r.location.code));
      const mf = $("#l-mvfrom"); if (mf) mf.addEventListener("click", () => go("move", r.location.code));
      const gp = $("#l-goput"); if (gp) gp.addEventListener("click", () => go("put", r.item.code));
      const gm = $("#l-gomove"); if (gm) gm.addEventListener("click", () => go("move", ((r.item.locs || {}).locations || [])[0].code));
      const od = $("#l-order"); if (od) od.addEventListener("click", () => go("order", r.order.order_no));
      view().querySelectorAll("[data-code]").forEach((li) => li.addEventListener("click", () => this.load(li.dataset.code, false).catch((e) => toast(e.message, true))));
    },
    async scan(code) {
      try { this.msg = null; await this.load(code); } catch (e) { SCAN.bad(); this.msg = ["bad", srv(e.message)]; this.render(); }
    },
  };

  // ---------------- 上架（v2.52）：扫商品 → 看推荐货位 → 扫货位确认 ----------------
  SCREENS.put = {
    list: [], it: null, at: null, msg: null,
    async show(arg) {
      this.it = null; this.at = null; this.msg = null;
      if (!INV) { view().innerHTML = lastMsg("bad", T("k.noinv")); return; }
      if (arg && arg.startsWith("@")) this.at = arg.slice(1);
      await this.load();
      if (arg && !arg.startsWith("@")) await this.scan(arg);
    },
    refresh() { this.load().catch(() => {}); },
    async load() {
      try { this.list = (await api("/api/inv/wms/pending")).items; } catch (e) { toast(srv(e.message), true); this.list = []; }
      if (this.it) this.it = this.list.find((x) => x.item.id === this.it.item.id) || null;
      this.render();
    },
    render() {
      const x = this.it;
      const msg = this.msg ? lastMsg(this.msg[0], this.msg[1]) : "";
      if (x) {
        const s = x.suggest || [];
        view().innerHTML = `${msg}<div class="card"><div class="row between"><div><div class="mono" data-notr><b>${esc(x.item.code)}</b></div><div class="nm" data-notr>${esc(nm(x.item.name_zh, x.item.name_th))}</div></div>
            <div style="text-align:right"><div class="small muted">${T("u.pending")}</div><div class="q" style="font-size:28px">${esc(qn(x.qty))}</div></div></div></div>
          <div class="card"><div class="small muted">${T("u.sug")}</div>${s.length ? s.map((p, i) => `<div class="row between sugrow ${i ? "" : "first"}"><span class="loc" data-notr style="font-size:${i ? 18 : 26}px">${esc(p.code)}</span>
              <span class="small">${p.qty ? "×" + esc(qn(p.qty)) + " · " : ""}${T("u.r." + p.reason)}</span></div>`).join("") : `<p class="warn">${T("u.nosug")}</p>`}</div>
          <div class="card col"><div class="small muted">${T("u.qty")}</div>
            <div class="step"><button id="p-minus">−</button><input id="p-qty" type="number" inputmode="decimal" value="${esc(qn(s[0] && s[0].qty ? s[0].qty : x.qty))}"><button id="p-plus">+</button></div>
            <div class="mode">${T("u.scanloc")}</div>
            <button class="big" id="p-back">${T("u.back")}</button></div>`;
        const q = $("#p-qty");
        $("#p-minus").addEventListener("click", () => { q.value = Math.max(0, qn(q.value) - 1); });
        $("#p-plus").addEventListener("click", () => { q.value = qn(q.value) + 1; });
        $("#p-back").addEventListener("click", () => { this.it = null; this.msg = null; this.render(); });
        return;
      }
      view().innerHTML = `${msg}<p class="hint"><span class="big-ic">📥</span>${this.at ? T("u.scanat", { l: this.at }) : T("u.scan")}</p>
        <div class="card"><b>${T("u.list")}</b>${this.list.length ? `<ul class="list">${this.list.map((y) => `<li class="tap" data-iid="${y.item.id}"><div class="grow"><div class="mono" data-notr><b>${esc(y.item.code)}</b></div>
          <div class="small" data-notr>${esc(nm(y.item.name_zh, y.item.name_th))}</div><div class="small muted" data-notr>→ ${esc((y.suggest[0] || {}).code || "—")}</div></div><b>${esc(qn(y.qty))}</b></li>`).join("")}</ul>`
          : `<p class="muted">${T("u.none")}</p>`}</div>`;
      view().querySelectorAll("[data-iid]").forEach((li) => li.addEventListener("click", () => { this.it = this.list.find((y) => y.item.id === +li.dataset.iid); this.msg = null; this.render(); }));
    },
    async put(code, force) {
      const x = this.it, qty = qn($("#p-qty") ? $("#p-qty").value : x.qty);
      try {
        const r = await send("/api/inv/wms/putaway", { item_id: x.item.id, code, qty, force: !!force, from: x.from || "" }, `${T("t.put")} ${x.item.code} → ${code}`);
        SCAN.ok();
        this.msg = r.queued ? ["warn", T("offline.q")] : ["ok", T("l.put_ok", { c: `${x.item.code} ×${qty}`, l: code })];
        this.it = null;
        await this.load();
      } catch (e) {
        SCAN.bad();
        if (/放不下/.test(e.message) && !force && (await confirmBox(srv(e.message) + "\n" + T("u.force")))) return this.put(code, true);
        this.msg = ["bad", srv(e.message)]; this.render();
      }
    },
    async scan(code) {
      try {
        const r = await api(`/api/mobile/resolve?prefer=location&code=${encodeURIComponent(code)}`);
        if (r.type === "location") {
          if (this.it) return this.put(r.location.code);
          SCAN.ok(); this.at = r.location.code; this.msg = null; this.render(); return;
        }
        if (r.type === "item") {
          const y = this.list.find((z) => z.item.id === r.item.id);
          if (!y) { SCAN.warn(); this.msg = ["warn", T("u.notpending", { c: r.item.code })]; this.render(); return; }
          SCAN.ok(); this.it = y; this.msg = null;
          if (this.at) { this.render(); return this.put(this.at); }
          this.render(); return;
        }
        SCAN.bad(); this.msg = ["bad", T("unknown", { c: code })]; this.render();
      } catch (e) { SCAN.bad(); this.msg = ["bad", srv(e.message)]; this.render(); }
    },
  };

  // ---------------- 料卷（v2.53）：扫料卷 → 扫货位放好 / 扫打印机 · 槽上机；下机、称重盘点、用完 ----------------
  SCREENS.spool = {
    sp: null, msg: null,
    async show(arg) { this.sp = null; this.msg = null; if (!INV) { view().innerHTML = lastMsg("bad", T("k.noinv")); return; } if (arg) await this.scan(arg); else this.render(); },
    async open(code) { this.sp = (await api(`/api/inv/spools/${encodeURIComponent(code)}`)).spool; },
    render() {
      const s = this.sp, msg = this.msg ? lastMsg(this.msg[0], this.msg[1]) : "";
      if (!s) { view().innerHTML = `${msg}<p class="hint"><span class="big-ic">🧵</span>${T("s.scan")}</p>`; return; }
      const where = s.loc ? `<span class="loc" data-notr>${esc(s.loc.code)}</span><div class="small" data-notr>${esc(TH() ? s.loc.human_th : s.loc.human_zh)}</div>` : `<b class="warn">${T("s.none")}</b>`;
      view().innerHTML = `${msg}<div class="card"><div class="row between"><div><div class="mono" data-notr><b>${esc(s.code)}</b></div><div class="nm" data-notr>${esc(s.material)} ${esc(s.color)} ${esc(s.brand || "")}</div></div>
          <div style="text-align:right"><div class="small muted">${T("s.left")}</div><div class="q" style="font-size:26px">${esc(Math.round(s.remaining_g || 0))} g</div></div></div>
          <div class="small muted" style="margin-top:6px">${T("s.where")}</div>${where}</div>
        <div class="card col"><div class="mode">${T("s.then")}</div>
          ${s.status === "loaded" ? `<button class="big" id="s-unload">${T("s.unload")}</button>` : ""}
          <div class="small muted">${T("s.gross")}</div><div class="step"><input id="s-gross" type="number" inputmode="decimal" placeholder="g"><button id="s-weigh">${T("s.weigh")}</button></div>
          <button class="big" id="s-empty">${T("s.empty")}</button></div>`;
      const run = async (fn) => { try { await fn(); SCAN.ok(); } catch (e) { SCAN.bad(); this.msg = ["bad", srv(e.message)]; } this.render(); };
      const u = $("#s-unload"); if (u) u.addEventListener("click", () => run(async () => { this.sp = (await api(`/api/inv/spools/${s.code}/unload`, { json: {} })).spool; this.msg = ["ok", T("s.ok", { c: s.code, l: T("s.none") })]; }));
      $("#s-weigh").addEventListener("click", () => run(async () => {
        const r = await api(`/api/inv/spools/${s.code}/weigh`, { json: { gross: +$("#s-gross").value } });
        this.sp = r.spool; this.msg = ["ok", T("s.wok", { c: s.code, g: Math.round(r.result.after), d: (r.result.diff >= 0 ? "+" : "") + Math.round(r.result.diff) })];
      }));
      $("#s-empty").addEventListener("click", async () => { if (!(await confirmBox(T("s.emptyq", { c: s.code })))) return; run(async () => { await api(`/api/spools/${s.code}/empty`, { json: {} }); this.sp = null; this.msg = ["ok", "✔ " + s.code]; }); });
    },
    async scan(code) {
      try {
        const r = await api(`/api/mobile/resolve?prefer=location&code=${encodeURIComponent(code)}`);
        if (r.type === "spool") { SCAN.ok(); this.msg = null; await this.open(r.spool.code); this.render(); return; }
        if (r.type === "location" && this.sp) {
          const x = await api(`/api/inv/spools/${this.sp.code}/put`, { json: { code: r.location.code } });
          SCAN.ok(); this.msg = ["ok", T("s.ok", { c: this.sp.code, l: r.location.code })]; this.sp = x.spool; this.render(); return;
        }
        SCAN.bad(); this.msg = ["bad", this.sp ? T("unknown", { c: code }) : T("s.scan")]; this.render();
      } catch (e) { SCAN.bad(); this.msg = ["bad", srv(e.message)]; this.render(); }
    },
  };

  // ---------------- 质检 / 退货（v2.53）：列表 → 点一个 → 扫货位上架（或推荐）/ 次品区 / 报废 ----------------
  function heldScreen(zt, cfg) {
    return {
      list: [], defect: [], it: null, msg: null,
      async show(arg) { this.it = null; this.msg = null; if (!INV) { view().innerHTML = lastMsg("bad", T("k.noinv")); return; } await this.load(); if (arg) await this.scan(arg); },
      async load() {
        try { this.list = (await api("/api/inv/held/" + zt)).items; } catch (e) { this.list = []; toast(srv(e.message), true); }
        if (cfg.defect) { try { this.defect = (await api("/api/inv/held/defect")).items; } catch { this.defect = []; } }
        if (this.it) this.it = this.list.find((x) => x.item.id === this.it.item.id && x.from === this.it.from) || null;
        this.render();
      },
      render() {
        const msg = this.msg ? lastMsg(this.msg[0], this.msg[1]) : "", x = this.it;
        if (x) {
          const sug = (x.suggest || [])[0];
          view().innerHTML = `${msg}<div class="card"><div class="row between"><div><div class="mono" data-notr><b>${esc(x.item.code)}</b></div><div class="nm" data-notr>${esc(nm(x.item.name_zh, x.item.name_th))}</div>
              <div class="small muted" data-notr>${esc(x.from)}</div></div><div class="q" style="font-size:28px">${esc(qn(x.qty))}</div></div></div>
            <div class="card col"><div class="step"><button id="h-minus">−</button><input id="h-qty" type="number" inputmode="decimal" value="${esc(qn(x.qty))}"><button id="h-plus">+</button></div>
              <div class="mode">${T(cfg.go)}</div>${sug ? `<button class="big" id="h-sug">${T("q.sug", { l: sug.code })}</button>` : ""}
              <button class="big" id="h-bad">${T(cfg.bad)}</button>${cfg.scrap ? `<button class="big" id="h-scrap">${T("q.scrap")}</button>` : ""}
              <button class="big" id="h-back">${T("u.back")}</button></div>`;
          const q = $("#h-qty");
          $("#h-minus").addEventListener("click", () => { q.value = Math.max(0, qn(q.value) - 1); });
          $("#h-plus").addEventListener("click", () => { q.value = Math.min(qn(x.qty), qn(q.value) + 1); });
          $("#h-back").addEventListener("click", () => { this.it = null; this.msg = null; this.render(); });
          if (sug) $("#h-sug").addEventListener("click", () => this.good(sug.code));
          $("#h-bad").addEventListener("click", () => this.bad(false));
          const sc = $("#h-scrap"); if (sc) sc.addEventListener("click", async () => { if (await confirmBox(T("q.scrap") + "?")) this.bad(true); });
          return;
        }
        const li = (y, k) => `<li class="tap" data-h="${k}"><div class="grow"><div class="mono" data-notr><b>${esc(y.item.code)}</b></div><div class="small" data-notr>${esc(nm(y.item.name_zh, y.item.name_th))}</div>
          <div class="small muted" data-notr>${esc(y.from)}${y.suggest && y.suggest[0] ? " → " + esc(y.suggest[0].code) : ""}</div></div><b>${esc(qn(y.qty))}</b></li>`;
        view().innerHTML = `${msg}<div class="card"><b>${T(cfg.list)}</b>${this.list.length ? `<ul class="list">${this.list.map((y, i) => li(y, i)).join("")}</ul>` : `<p class="muted">${T(cfg.none)}</p>`}</div>
          ${cfg.defect && this.defect.length ? `<div class="card"><b>${T("r.def")}</b><ul class="list">${this.defect.map((y) => `<li><div class="grow mono" data-notr>${esc(y.item.code)} · ${esc(y.from)}</div><b>${esc(qn(y.qty))}</b></li>`).join("")}</ul></div>` : ""}`;
        view().querySelectorAll("[data-h]").forEach((el) => el.addEventListener("click", () => { this.it = this.list[+el.dataset.h]; this.msg = null; this.render(); }));
      },
      qty() { return qn($("#h-qty") ? $("#h-qty").value : this.it.qty); },
      async good(to) {
        const x = this.it, qty = this.qty();
        try {
          const r = await api(cfg.goodUrl, { json: { item_id: x.item.id, from: x.from, qty, to, act: "restock" } });
          SCAN.ok(); this.msg = ["ok", T("l.put_ok", { c: `${x.item.code} ×${qty}`, l: r.to })]; this.it = null; await this.load();
        } catch (e) { SCAN.bad(); this.msg = ["bad", srv(e.message)]; this.render(); }
      },
      async bad(scrap) {
        const x = this.it, qty = this.qty();
        try {
          const r = await api(cfg.badUrl, { json: { item_id: x.item.id, from: x.from, qty, action: scrap ? "scrap" : "defect", act: scrap ? "scrap" : "defect", note: scrap ? T("q.scrap") : "" } });
          SCAN.warn(); this.msg = ["warn", T("l.put_ok", { c: `${x.item.code} ×${qty}`, l: r.to || "" })]; this.it = null; await this.load();
        } catch (e) { SCAN.bad(); this.msg = ["bad", srv(e.message)]; this.render(); }
      },
      async scan(code) {
        try {
          const r = await api(`/api/mobile/resolve?prefer=location&code=${encodeURIComponent(code)}`);
          if (r.type === "location" && this.it) return this.good(r.location.code);
          const id = r.item ? r.item.id : null;
          const y = id ? this.list.find((z) => z.item.id === id) : null;
          if (y) { SCAN.ok(); this.it = y; this.msg = null; this.render(); return; }
          if (cfg.receive && (r.item || r.sku)) {
            const c = r.item ? r.item.code : r.sku.sku;
            const n = prompt(T("r.newq", { c }), "1"); if (!n) return;
            await api("/api/inv/returns/receive", { json: r.item ? { item_id: r.item.id, qty: +n } : { code: c, qty: +n } });
            SCAN.ok(); this.msg = ["ok", T("r.added", { c, n })]; await this.load(); return;
          }
          SCAN.bad(); this.msg = ["bad", T("unknown", { c: code })]; this.render();
        } catch (e) { SCAN.bad(); this.msg = ["bad", srv(e.message)]; this.render(); }
      },
    };
  }
  SCREENS.qc = heldScreen("qc", { list: "q.list", none: "q.none", go: "q.pass", bad: "q.fail", scrap: true, goodUrl: "/api/inv/qc/pass", badUrl: "/api/inv/qc/fail" });
  SCREENS.ret = heldScreen("returns", { list: "r.list", none: "r.none", go: "r.restock", bad: "r.todef", defect: true, receive: true, goodUrl: "/api/inv/returns/act", badUrl: "/api/inv/returns/act" });

  // ---------------- 移库（v2.52）：扫原货位 → 扫商品（一下 +1）→ 扫目标货位；补货任务点一下照着做 ----------------
  SCREENS.move = {
    from: null, lines: {}, task: null, tasks: [], msg: null,
    async show(arg) {
      this.from = null; this.lines = {}; this.task = null; this.msg = null;
      if (!INV) { view().innerHTML = lastMsg("bad", T("k.noinv")); return; }
      await this.loadTasks();
      if (arg) await this.scan(arg); else this.render();
    },
    refresh() { this.loadTasks().then(() => this.render()).catch(() => {}); },
    async loadTasks() { try { this.tasks = (await api("/api/inv/wms/tasks")).tasks; } catch { this.tasks = []; } },
    async setFrom(code) {
      const r = await api(`/api/inv/locations/find?code=${encodeURIComponent(code)}`);
      this.from = { code: r.location.code, items: (r.items || []).filter((x) => x.qty > 1e-9) };
      this.lines = {};
    },
    render() {
      const msg = this.msg ? lastMsg(this.msg[0], this.msg[1]) : "";
      const f = this.from;
      const n = Object.values(this.lines).filter((v) => v > 0).length;
      const step = !f ? 1 : !n ? 2 : 3;
      view().innerHTML = `${msg}
        <div class="card steps"><div class="${step === 1 ? "on" : "done"}">① ${T("m.s1")}${f ? ` <b class="mono" data-notr>${esc(f.code)}</b>` : ""}</div>
          <div class="${step === 2 ? "on" : step > 2 ? "done" : ""}">② ${T("m.s2")}</div><div class="${step === 3 ? "on" : ""}">③ ${T("m.s3")}${this.task ? ` <b class="mono" data-notr>${esc(this.task.to_loc)}</b>` : ""}</div></div>
        ${f ? `<div class="card"><div class="row between"><span class="loc" data-notr>${esc(f.code)}</span><button class="sm" id="m-reset">${T("m.reset")}</button></div>
          ${f.items.length ? `<ul class="list">${f.items.map((x) => { const v = this.lines[x.id] || 0; return `<li><div class="grow"><div class="mono" data-notr><b>${esc(x.code)}</b></div>
            <div class="small" data-notr>${esc(nm(x.name_zh, x.name_th))}</div><div class="small muted">${T("m.have")} ${esc(qn(x.qty))}</div></div>
            <div class="step" style="width:150px"><button class="sm" data-dec="${x.id}">−</button><input type="number" inputmode="decimal" data-q="${x.id}" value="${v || ""}" placeholder="0" style="min-height:40px;font-size:18px;padding:4px"><button class="sm" data-inc="${x.id}">+</button></div>
            <button class="sm" data-all="${x.id}">${T("m.all")}</button></li>`; }).join("")}</ul>` : `<p class="muted">${T("l.empty")}</p>`}</div>` : ""}
        ${!f && this.tasks.length ? `<div class="card"><b>${T("m.tasks")}</b><ul class="list">${this.tasks.map((t) => `<li class="tap" data-task="${t.id}"><div class="grow"><div class="mono" data-notr><b>${esc(t.code)}</b> ×${esc(qn(t.qty))}</div>
          <div class="small" data-notr>${esc(t.from_loc)} → ${esc(t.to_loc)}</div></div><span class="small muted">${T("m.repl")}</span></li>`).join("")}</ul></div>` : ""}`;
      const it = (id) => (f ? f.items.find((x) => x.id === +id) : null);
      const setq = (id, q) => { const x = it(id); this.lines[id] = Math.max(0, Math.min(qn(q), x ? qn(x.qty) : qn(q))); this.render(); };
      view().querySelectorAll("[data-inc]").forEach((b) => b.addEventListener("click", () => setq(b.dataset.inc, (this.lines[b.dataset.inc] || 0) + 1)));
      view().querySelectorAll("[data-dec]").forEach((b) => b.addEventListener("click", () => setq(b.dataset.dec, (this.lines[b.dataset.dec] || 0) - 1)));
      view().querySelectorAll("[data-all]").forEach((b) => b.addEventListener("click", () => setq(b.dataset.all, (it(b.dataset.all) || {}).qty)));
      view().querySelectorAll("[data-q]").forEach((inp) => inp.addEventListener("change", () => setq(inp.dataset.q, inp.value)));
      const rs = $("#m-reset"); if (rs) rs.addEventListener("click", () => { this.from = null; this.lines = {}; this.task = null; this.msg = null; this.render(); });
      view().querySelectorAll("[data-task]").forEach((li) => li.addEventListener("click", async () => {
        const t = this.tasks.find((x) => x.id === +li.dataset.task);
        try { await this.setFrom(t.from_loc); this.task = t; this.lines[t.item_id] = Math.min(qn(t.qty), qn(t.available)); this.msg = ["warn", T("m.dotask", { l: t.to_loc })]; this.render(); }
        catch (e) { toast(srv(e.message), true); }
      }));
    },
    async doMove(to, force) {
      const lines = Object.entries(this.lines).filter(([, q]) => q > 0).map(([id, q]) => ({ item_id: +id, qty: q }));
      const body = { from: this.from.code, to, lines, force: !!force };
      if (this.task && this.task.to_loc === to) body.task_id = this.task.id;
      try {
        const r = await send("/api/inv/wms/move", body, `${T("t.move")} ${this.from.code} → ${to}`);
        SCAN.ok();
        this.msg = r.queued ? ["warn", T("offline.q")] : ["ok", T("m.ok", { f: this.from.code, t: to, n: lines.length })];
        this.from = null; this.lines = {}; this.task = null;
        await this.loadTasks();
      } catch (e) {
        SCAN.bad();
        if (/放不下/.test(e.message) && !force && (await confirmBox(srv(e.message) + "\n" + T("u.force")))) return this.doMove(to, true);
        this.msg = ["bad", srv(e.message)];
      }
      this.render();
    },
    async scan(code) {
      try {
        const k = code.trim().toUpperCase();
        if (this.from) {
          const x = this.from.items.find((y) => String(y.code).toUpperCase() === k);
          if (x) { SCAN.ok(); this.lines[x.id] = Math.min(qn((this.lines[x.id] || 0) + 1), qn(x.qty)); this.msg = ["ok", `✔ ${x.code}  ${this.lines[x.id]}`]; this.render(); return; }
        }
        const r = await api(`/api/mobile/resolve?prefer=location&code=${encodeURIComponent(code)}`);
        if (r.type === "location") {
          const has = Object.values(this.lines).some((q) => q > 0);
          if (this.from && has) return this.doMove(r.location.code);
          SCAN.ok(); await this.setFrom(r.location.code); this.task = null; this.msg = null; this.render(); return;
        }
        if (r.type === "item") { SCAN.warn(); this.msg = ["warn", this.from ? T("m.notfrom", { c: r.item.code, l: this.from.code }) : T("m.s1")]; this.render(); return; }
        SCAN.bad(); this.msg = ["bad", T("unknown", { c: code })]; this.render();
      } catch (e) { SCAN.bad(); this.msg = ["bad", srv(e.message)]; this.render(); }
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
            <input data-r="loc" placeholder="${esc(l.putaway && l.putaway[0] ? T("r.sug", { l: l.putaway[0].code }) : T("r.loc"))}" value="${esc(l.location || "")}" style="margin-top:8px" data-notr>
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
