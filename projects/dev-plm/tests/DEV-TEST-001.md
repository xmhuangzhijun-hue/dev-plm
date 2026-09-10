---
id: DEV-TEST-001
title: 第2轮基线已有验收回执
req: DEV-REQ-008
env: 本地
result: 原有13项回归本轮再次通过
expected: 改文件后重建页面变化、断链时报文件行号，离线网页可用。
actual: 本轮执行 python -m unittest discover -s tests -v，原第2轮13项均通过，包含源文件改动后重建更新、断链报文件行号并保留旧站点。历史回执仍保留。
record: DEV-LOG-001
---

本单明确区分历史回执、当前候选资料与本轮实际测试结果。
