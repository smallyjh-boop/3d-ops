# 模块：手机 / 平板 App（mobile）

员工拿手机扫码干活的页面 **/m**，加上安卓 App（源码在根目录 `android/`）的服务器这一边。

- **手机（/m）**：查订单、扫码发货交接、验货（显示「去 A1-02-03 拿」）、库存（入库 / 出库 / 改成实数）、货位（里面有什么 / 东西在哪些货位）、上架（扫商品 → 按推荐扫货位）、移库（扫原货位 → 商品 → 新货位，补货任务）、按货位盘点（v2.52）。
  上面一条摄像头小窗（屏幕 1/4）一直开着、像扫码枪一样连续扫；蓝牙 / USB 扫码枪（键盘输入）和手动输入也都行。
  中文 / 泰文（右上角切换，跟网页版共用 `ui_lang`）。没登录时页面自己显示登录框（`/m` 不用登录也能打开）。
- **平板**：安卓 App 在平板上打开完整网页版「/」。App 的 User-Agent 带 `3DOpsApp/<版本>`，首页 `<html class="in-app">`
  （web/system.py），`static/style.css` 把电脑才有的东西藏起来（电脑加速器、桌面版下载）；触屏的按钮 / 输入框放大、
  顶部菜单一行横着滑、宽表格在卡片里横着滑（`ui/boot.js` 套 `.tbl-scroll`）。
- **安卓 App 下载**：设置 → 组件与插件 → 安卓 App。NAS 从 GitHub Release（`android-v<版本>`，`.github/workflows/android.yml` 编译）
  取 APK 存在 `data/android/`，手机在局域网里打开 `http://NAS:8790/apk` 下载（不用登录、不用连 GitHub）；连不上 GitHub 时老板可以手动上传 APK。

## 扫码怎么认（resolver.py）

`GET /api/mobile/resolve?code=…&prefer=order|item|location&fresh=1` → `{type, …}`：

| 扫到的 | 哪来的标签 | type |
|---|---|---|
| 订单号 / 快递单号（去掉 `-`、空白也认） | 面单（自制 / 平台）、装箱单 | `order`（带商品图、定制要求、生产进度、交接单、照片数；取消 / 退货 / 拒收带 `alert.level = error`） |
| 库存物品编码（成品就是 SKU） | 货位里的物品、商品标签、内部商品标签、生产工单贴纸 | `item`（数量、货位、可用成品；员工看不到成本） |
| 产品 SKU，还没建库存档 | 同上 | `sku` |
| 货位 `A1-02-03`（`a1-2-3` 也认）/ 货架 `A1` / 区 `A` | 货位标签、货架牌 | `location` / `shelf` / `zone` |
| 料卷编号 | 料卷标签 | `spool` |
| 都不是 | | `unknown` |

查询时订单号和快递单号都认（不管设置里「打包与交接扫什么码」）；验货和交接照样走订单模块原来的接口，按设置认码、先从平台同步状态、拦住取消的单。

## 手机页用的接口

- 新的：`/api/mobile/boot`、`/api/mobile/resolve`、`/api/mobile/orders?q=`（订单号 / 运单号 / 买家 / 电话模糊查）、`/api/mobile/orders/<id>`、
  `/api/mobile/carriers`（待发货订单的物流 + 没交完的交接单）、`/api/mobile/orders/<id>/photos`（打包照片：GET 列表 / POST 上传 / GET 照片）、
  `/api/mobile/apk`（安装包状态）、`/api/mobile/apk/fetch|check|upload`（老板）、`/apk` 和 `/api/mobile/apk/download`（下载，不用登录）。
- 现成的：验货 `/api/pack/lookup` + `/api/pack/done`；交接 `/api/handovers…`；出入库 `/api/inv/docs`；盘点 `/api/inv/stocktake…`；
  放货位 `/api/inv/locations/assign`；订单状态权限、库存权限（inv.in / inv.out / inv.adjust）都按原来的规矩。
- 生产打包角色能用手机页（module.py 的 production_allow）。

## 断网

交接扫码、出入库、放货位、验货完成：网络断了先存在手机里（localStorage `m3d_queue`），右上角显示 ⏳ 几条，联网后每 10 秒自动补传；
补传时被服务器拒绝的（例如订单这期间被取消了）长鸣 + 红屏提醒，列在 ⚠ 里。查询类（查订单、看库存）断网时提示连不上。

## 打包照片

验货完成后可以拍一张（也可以在「查订单」里拍）：存在 `data/order_photos/<订单 id>/`，缩到长边 1600 像素的 JPG，记在订单的操作记录里；
网页版订单详情里显示（订单模块 2.2）。

## 文件

- `module.py`        说明书（public_exact：`/m`、`/apk` 不用登录；public_paths：手机页的 js / css、安装包下载）
- `api.py`           接口
- `resolver.py`      扫码识别、订单摘要、查订单、交接选物流
- `photos.py`        订单的打包照片
- `apk.py`           安卓安装包（从 GitHub Release 取 / 手动上传）
- `ui/m.html`        手机页（/m）
- `ui/m.js`          手机页的各个页面、断网排队、中文 / 泰文
- `ui/m.css`         手机页样式
- `ui/scan.js`       扫码：原生摄像头（App）/ BarcodeDetector（浏览器，要 https）/ 扫码枪 / 手输，去重，声音震动闪屏
- `ui/page.js`       设置 → 组件与插件 → 安卓 App 卡片
- `ui/boot.js`       网页版：平板宽表格横着滑、App 里顶部「📱 扫码」「⚙」
- `i18n/th.json`     泰文（设置卡片、后台提示）
- `tests/t_mobile.py`

内核里配合改的：`core/auth.py`（PUBLIC_EXACT）、`core/modules.py`（说明书 public_exact）、`web/system.py`（App 的 User-Agent → `html.in-app`）、
`static/style.css`（平板 / 触屏、in-app 隐藏）、`core/sysadmin.py`（在线升级不复制 `android/`）、订单模块 `ui/orders.js`（订单详情的打包照片）。

## 安卓 App（根目录 android/）

Kotlin + Gradle Kotlin DSL，minSdk 24 / targetSdk 34，AGP 8.7.3、Kotlin 2.0.21、Gradle 8.11.1、CameraX 1.3.4、ML Kit barcode-scanning 17.3.0（模型打包在 App 里）。

- `MainActivity.kt`   WebView 外壳：平板（sw600dp）打开「/」、手机打开「/m」（设置里可以换）；User-Agent 加 `3DOpsApp/<版本>`；允许 http；
  同一个服务器的链接在 App 里开，别的网站用手机浏览器；拍照 / 选照片上传（FileProvider）；下载（面单 PDF 等，DownloadManager 带登录 cookie）；
  `window.print()` 换成安卓打印；返回键退网页历史，到头了问「退出 / 设置」；连不上服务器显示「重试 / 设置」。
- `Scanner.kt`        上面一条摄像头小窗（屏幕 1/4）：CameraX 预览 + ML Kit 连续识别，同一个码 2 秒内一直看得到只算一次，读到的码
  `evaluateJavascript("window.onNativeScan && window.onNativeScan(code)")`；手电筒；扫码时屏幕常亮。
- `WebBridge.kt`      `window.Android3D`：isApp / isTablet / version / startScan / stopScan / beep(ok|warn|error) / openSettings / print。
- `Feedback.kt`       ToneGenerator + 震动（成功短嘀、警告两声、出错长鸣长震）。
- `SettingsActivity.kt` 服务器地址（默认 http://192.168.31.200:8790，先测 /api/version 再保存）、打开哪个版本（自动 / 网页版 / 手机版）。
- 签名：`app/debug.keystore`（固定的，每次编译签名一样，手机上能覆盖安装）；GitHub Secrets 放了正式密钥就用正式的。
- 编译：`cd android && ./gradlew assembleRelease`（要 Android SDK 34）。GitHub：`.github/workflows/android.yml`，android/ 有改动推到 main
  → 编译 debug + release APK → Actions 产物 + Release `android-v<versionName>`。改了 App 记得把 `app/build.gradle.kts` 的 versionCode / versionName 加一。
- 平板的网页版里（App 内）：「打包核对」「发货交接」的 📷 按钮用原生摄像头（ui/boot.js 把码送进扫码框）。

## 改动记录

- 1.0（系统 v2.47.0）：新模块。手机扫码页 /m（查订单、扫码发货交接、验货、库存、盘点、货位，摄像头连续扫 + 扫码枪 + 手输，去重，
  成功 / 警告 / 出错不同的声音震动，断网排队补传，中文 / 泰文）、扫码识别接口、打包照片、安卓 App 安装包（GitHub Release / 手动上传、`/apk` 下载）、
  平板触屏样式和 App 里隐藏电脑才有的功能。
- 1.1（系统 v2.51.0）：手机页加「采购到货」（扫采购单号 / 物流单号 / 物品条码，一件一扫点数，记少发 / 破损，放货位，打印物品标签，断网排队补传；采购模块开着才有）。
- （系统 v2.52.0，配合拍照识别模块 recog）：扫码输入框旁边「📷 识别」（拍照找产品 / 拍照读文字，认出来的码像扫码一样送给当前页面，脚本在 `modules/recog/ui/`）；
  App 摄像头认出的文字 `onNativeScan(文字, "text")` 先经 `/api/recog/text` 容错认成系统里的码（`scan.js` 显示「文字」小标）；
  `GET /api/mobile/resolve?…&fuzzy=1` 认不出时按文字容错（O/0、I/1、少横杠）找最像的码；新接口 `GET /api/mobile/code-patterns`（App 挑「像码的文字」的正则）。
