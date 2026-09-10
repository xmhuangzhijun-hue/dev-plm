---
id: DEMO-LOG-007
time: 09-04 18:10
stage: 前端
env: 本地
reqs:
- DEMO-REQ-001
title: 任务列表增加截止日期与到期提醒
result: 示例完成
target: '#screens/task-list'
actor: 前端开发者（示例）
before: 只显示任务名称
after: 显示名称、完成状态与日期
---

从页面字段映射到 GET /v1/tasks 的 due_date；不在前端保存另一份权威状态。
