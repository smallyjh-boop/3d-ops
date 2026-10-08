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
