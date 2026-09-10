# OpenAPI 3.1 离线校验

本模块已用于 dev-plm 的离线构建。2026-09-05 用户明确允许使用本机已有 jsonschema 完成官方 Schema 校验；未安装或升级软件。依赖为 jsonschema 及其 referencing 依赖，不能宣称为纯标准库实现。

## 用法

保持 `validate_openapi.py`、`SOURCES.json`、`schemas/` 相对位置不变：

```python
from validate_openapi import validate_spec
errors = validate_spec(spec)
```

每条错误包含 `path`（键名/数组下标列表）、`pointer`（JSON Pointer）、`kind`、`message`。构建器负责把路径映射为源文件行号并非零退出。CLI 也支持 `python validate_openapi.py path/to/openapi.json`。

## 使用的正式上游

- [OpenAPI 官方 schema 目录及其边界说明](https://spec.openapis.org/oas/)：普通 `schema` 不检查 Schema Object，`schema-base` 才检查；官方明确 schema 不能保证覆盖全部规范语义。
- [OpenAPI 3.1 schema-base 2025-11-23](https://spec.openapis.org/oas/3.1/schema-base/2025-11-23.html)，配套 schema 同日版本；dialect/meta 使用 2024-11-10。
- [JSON Schema 2020-12 上游固定版本](https://github.com/json-schema-org/json-schema-spec/tree/2020-12)。`json-schema.org` 原站下载在本次环境返回 403，因此从规范作者的官方固定版本仓库获取。
- [jsonschema Registry 用法](https://python-jsonschema.readthedocs.io/en/stable/referencing/)：只注册仓库随附资源，未知资源回调直接报错，不联网读取。

所有官方文件原样保存，来源及 SHA-256 见 `SOURCES.json`，原始许可证见 `licenses/`。模块初始化检查全部 schema 的 SHA-256。

## 动态引用、方言和诚实边界

1. 官方 schema-base 用 `$dynamicRef` / `$dynamicAnchor` 把 Schema Object 校验接入 2020-12 元模式。本模块实际运行此机制，没有把它简化成“有 openapi/info 字段即通过”。
2. `jsonschema 4.26.0` 当前环境对 schema-base 内 Schema Object 显式 `$schema` 的相对引用出现 `PointerToNowhere`。候选只在内存副本将一个 `#/$defs/dialect` 等价绝对化为 schema-base 的完整 URI；磁盘上游文件保持原样。允许的显式方言与省略方言都经过测试，其他方言按官方 const 约束报错。此单点兼容处理见模块注释。
3. 此候选的引用完整性检查面向**单文件契约**：检查 `#/...` JSON Pointer 和本地 anchor；外部 `$ref` 与嵌套 `$id` 资源显式拒绝，不联网、不忽略。Schema Object 子节点遍历复用 `referencing` 的 2020-12 实现，示例原始数据里的 `$ref` 不当作契约引用。
4. 不宣称覆盖全部 OpenAPI 语义：例如全局 `operationId` 唯一性、路径模板和参数对应、security 名称有效性，以及请求/响应实例符合业务行为，仍需独立项目校验/测试。官方 schema 的通过不能证明后端存在或接口联调成功。
5. 使用 2020-12 的 format annotation 默认语义，不声称全部 format assertion。本机未安装 URI、date-time 等格式可选依赖；不偷报“完整格式验证成功”。
6. 本模块不处理 `x-requirements`，主构建器应在各项目已建立 ID 索引后检查这类业务引用及源行号。任何模块缺失、资源校验失败、解析故障都会返回阻断错误。
