---
description: 生成规范的提交信息并提交（Haiku）
model: haiku
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git log:*)
---
1. 看 `git status` 和 `git diff`。
2. 按格式写提交信息：`feat: / fix: / refactor: / docs:` + 中文说明，一行标题，必要时加 2–3 行正文。
3. 如果改动包含多件不相关的事，建议我拆成几次提交，先问我。
4. 否则 `git add -A` 并提交，回复提交信息。不要 push。
