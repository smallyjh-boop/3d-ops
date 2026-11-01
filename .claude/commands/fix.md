---
description: 修 bug：定位 → 最小改动修复 → 验证（Sonnet）
argument-hint: <现象 / 报错 / 文件路径>
model: sonnet
---
问题：$ARGUMENTS

1. 先定位根因：给了路径就直接看；没给就交给 code-searcher 查。
2. 用最小改动修复，不顺手重构其他代码。
3. 补一个能复现该 bug 的测试。
4. 交给 test-runner 验证。
5. 回复：根因一句话 + 改了什么。修 2 次仍失败就停下，告诉我建议用 /model opus 接手。
