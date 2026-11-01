---
description: 给现有项目自动填写 CLAUDE.md（Sonnet）
model: sonnet
---
交给 code-searcher 子代理，查看 package.json / pyproject / 目录结构 / 配置文件，弄清：
技术栈、常用命令、重要目录。

然后填写 CLAUDE.md 里所有 `<...>` 占位符，删掉项目用不到的行。
项目名称和一句话描述不确定就问我。整个 CLAUDE.md 保持在 80 行以内。
