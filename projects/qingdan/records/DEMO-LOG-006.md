---
id: DEMO-LOG-006
time: 09-04 17:40
stage: 后端
env: 测试
reqs:
- DEMO-REQ-001
title: 创建与读取接口增加可空日期
result: 示例完成
target: '#apis/createTask'
actor: 后端开发者（示例）
before: 无日期字段
after: 契约中有可空截止日期
---

请求支持 due_date 为 null；补充自然日语义和幂等请求规则。
