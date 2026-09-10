---
id: DEMO-LOG-010
time: 09-05 10:40
stage: 审计
env: 测试
reqs:
- DEMO-REQ-001
title: 记录任务修改的操作者与归属
result: 示例记录
target: '#data/due_date'
actor: 示例用户 A
before: 截止日期为空
after: 截止日期为 2026-09-05
---

示例用户 A 修改自己的任务日期；包含主体、动作、对象、前后值和结果。
