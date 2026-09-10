---
id: DEMO-LOG-002
time: 09-03 15:10
stage: 后端
env: 本地
reqs:
- DEMO-REQ-002
title: 任务状态更新增加版本冲突处理
result: 示例修复
target: '#apis/updateTask'
actor: 后端开发者（示例）
before: 冲突时静默覆盖
after: 检测到旧版本后返回冲突
---

示例故障：两个客户端覆盖同一状态。用 revision 检测冲突，返回 409 供客户端处理。
