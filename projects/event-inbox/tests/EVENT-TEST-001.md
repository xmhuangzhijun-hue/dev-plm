---
id: EVENT-TEST-001
title: 相同事件重试返回相同回执
req: EVENT-REQ-001
env: 测试
result: 待执行
expected: 连续提交相同事件与相同幂等键，两次响应均为 202 且 receipt_id 相同，数据库仅一条事件。
actual: 尚无业务实现，没有实际执行回执。
record: EVENT-LOG-003
---

> 本条为虚构验收示例，不代表本轮实际执行过对应业务系统。
