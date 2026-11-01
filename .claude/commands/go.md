---
description: 执行 PLAN.md 里下一个未完成任务（Sonnet）
argument-hint: [可选：任务编号，如 T3]
model: sonnet
---
1. 读 docs/PLAN.md，执行任务 $ARGUMENTS；没指定就执行第一个未勾选的任务。只做这一个。
2. 只读该任务涉及的文件，找不到位置时交给 code-searcher。
3. 按 CLAUDE.md 规范实现，附带测试。
4. 交给 test-runner 跑测试和 lint，失败就修，最多修 3 轮，还不行就停下告诉我。
5. 在 PLAN.md 勾选该任务，更新 docs/HANDOVER.md。
6. 回复：改了哪些文件、为什么，3–5 行。
