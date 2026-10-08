# 模块开发规范（以后不管是修改还是新功能，都按这个来）

整个系统 = **内核**（登录权限、设置页框架、模块管理、电脑加速通道、在线升级）+ **modules/ 下的功能模块**。
改一个功能只动那个模块的文件夹；加一个功能就加一个文件夹或者在对应模块里加文件。

## 一个模块的文件夹

```
modules/<id>/
  module.py        说明书 MODULE = {...}：名字、版本、依赖、菜单、权限、设置、事件、页面文件
  api.py           接口：bp = Blueprint(...)；PREFIXES / PATTERNS 声明哪些地址属于这个模块（关掉时 404）
  <功能>.py         这个模块自己的逻辑（新功能写新文件，例如 orders/scanning.py、prod/slicecheck.py）
  logic/           逻辑多的模块放这里（cs、fin）
  ui/page.html     页面（每页一个 <section id="tab-…">）；inline 模块直接带进首页
  ui/*.js          页面脚本（page_js 打开时加载 / boot_js 一打开就加载 / eager_js 跟首页按顺序加载）
  ui/page.css      模块自己的样式
  i18n/th.json     这个模块的泰文翻译（中文原文 → 泰文）
  tests/t_*.py     这个模块的测试（tests/run_all.py 自动找到）
  README.md        说明 + 改动记录（每次改都在这里记一条）
```

## 规矩

1. **新功能先想放哪个模块**；跨模块的不直接调用对方，用 `core/chain.py` 的事件（`modules.emit`）或 `modules.public("<id>")`（对方关着返回 None）。
2. 设置项写在模块说明书的 `settings` 里（会出现在设置页对应的大分类），默认值写在 `config_defaults`。
3. 内核页面里属于某个模块的按钮 / 区块加 `data-needmod="<id>"`，模块关掉自动隐藏。
4. 新的文字同时写泰文翻译（模块的 `i18n/th.json`）。
5. 每个改动带测试（模块的 `tests/`），界面改动加到 `tests/ui/`。
6. 改完在模块 README 的「改动记录」和系统 README.txt 的版本说明里各记一条。
7. 删掉 / 搬走的文件写进根目录的 `removed_files.txt`，在线升级时会清掉旧文件。

主链路的数据层（产品、订单、生产、库存、耗材）还在 `core/`，几个模块共用；新的逻辑仍然写在模块里。

## 界面代码和翻译放哪（v2.34）

- 模块的页面脚本都放在模块的 `ui/` 里（`eager_js` 跟首页按顺序加载；`page_js` 打开页面才加载；`boot_js` 一打开就加载）。
  内核 `static/app.js` 只放大家都用的：`api` / `toast` / `busy`、权限 `CAN`、菜单和 `showTab`、设置页框架、账号、启动，
  公用小工具 `window.OPSH`（平台名、金额、日期、颜色、打印机名……）、API 密钥 `window.INTG_UI`。
- 页面打开时内核 `showTab` 会通知各页面对象：`window.OPS / PROD / HOME / FILES / SYS / AS / SHIP / PACK / INV` 的 `show(名字)`；
  新模块的页面用 MODKIT（`page_js`）或在模块脚本里自己挂一个对象。
- 模块脚本在内核脚本后面加载，模块之间按 `order`；加载时就要执行的代码只能用内核和排在前面的模块的东西，其余的放在函数里（点了 / 打开页面时才用）。
- 翻译：只在这个模块里用到的文字写在模块的 `i18n/th.json`；`static/i18n.js` 只留内核页面、几个模块共用的、后台程序（core/、web/）发出来的文字。
  首页打开时所有模块的 th.json 都会合进来（模块关着也合，不影响）。
- 3D 预览（`static/model3d.js`）、G-code 预览（`static/gview.js`）是几个模块共用的查看器（ES 模块），还在内核。

## 模块之间、弹窗、浏览器插件（v2.35）

- 给别的模块用的函数放在模块自己的一个文件里（例如 `inv/public.py`、`orders/packbox.py`），在说明书里写 `"public": 这个文件`；
  别的模块用 `modules.public("<id>")` 拿（对方关着返回 None，要判断）。现在有：`inv`（on_post / where_is / sort_key / human / order_out）、
  `orders`（box_for / set_box）。
- 共用弹窗 `MODAL.open()` 返回的是同一个框 `#modal-in`：事件用 `m.onclick / m.oninput / m.onchange = …`（关掉时清空），
  不要用 `addEventListener`（会一直留着，下一个弹窗里也会触发）。
- 浏览器插件在根目录 `extension/`（打包下载在客服模块 /api/cs/extension.zip，只打包这一层的文件）：一个功能一个文件，
  `background.js` 是公用的（cfg / callApi），面单转交在 `labels.js` + `pdfgrab.js`（后台消息都用 `label-` 开头），客服面板在 `content.js`。
  改了插件要改 manifest.json 的版本号和 `core/integrations.py` 的 `EXT_LATEST`。插件不读、不存平台的账号密码。
