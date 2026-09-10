---
id: EVENT-LOG-003
time: 09-05 11:15
stage: 测试
env: 测试
reqs:
- EVENT-REQ-001
title: 登记重试与内容冲突验收
result: 待执行
target: '#tests/EVENT-TEST-001'
actor: 测试负责人（示例）
before: 只有接口描述
after: 补充不重复保存与不覆盖的验收计划
---

测试计划同时核对响应回执与入库条数；相同 ID 不同内容必须失败。全部为待执行计划，不代表业务验证通过。
