---
id: EVENT-TEST-002
title: 相同编号不同内容返回冲突
req: EVENT-REQ-001
env: 测试
result: 待执行
expected: 相同调用方重用 event_id 并修改 payload，返回 409 / EVENT_CONFLICT；原事件不被覆盖。
actual: 尚无业务实现，没有实际执行回执。
record: EVENT-LOG-003
---

> 本条为虚构验收示例，不代表本轮实际执行过对应业务系统。
