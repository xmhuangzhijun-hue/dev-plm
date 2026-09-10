---
id: EVENT-LOG-005
time: 09-05 11:45
stage: 审计
env: 不适用
reqs:
- EVENT-REQ-001
- EVENT-REQ-002
title: 明确调用方归属的来源
result: 设计待实现
target: '#data/client_id'
actor: 服务负责人（示例）
before: 归属边界未写明
after: 服务身份决定事件与回执可见范围
---

虚构设计记录。client_id 从已验证令牌确定，不接受事件正文指定归属；审计记录将保留主体、动作、对象和结果，不记录凭据值。
