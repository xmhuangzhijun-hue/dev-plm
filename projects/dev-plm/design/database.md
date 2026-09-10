---
id: DEV-DESIGN-DATABASE
title: 文件派生读模型与协作真源的表结构设计
reqs:
  - DEV-REQ-002
  - DEV-REQ-003
  - DEV-REQ-008
  - DEV-REQ-009
  - DEV-REQ-010
  - DEV-REQ-011
  - DEV-REQ-012
status: 第4轮迁移代码已加入；真实数据库验收待环境确认
---

# 文件派生读模型与协作真源的表结构设计

本文定义 PostgreSQL 逻辑表与字段；第4轮对应迁移位于 backend/migrations/。当前尚未执行真实数据库验收，表结构存在于代码不等于数据库已运行。项目是什么由文件决定；数据库用于查询投影和明确限定的协作事务。

## 权威标记与恢复承诺

| 标记 | 真源 | 可直接改数据库吗 | 删库后的恢复依据 |
|---|---|---|---|
| F | 文件中的事实或明确声明 | 不可；先改文件再验证同步 | 项目文件、必要的删除标记与来源包 |
| G | 文件或 Git 客观派生值 | 不可；重新计算 | 相同文件与可用 Git 对象，使用同一投影版本 |
| D | 数据库协作真源 | 只允许经授权 API 与事务修改 | **必须有删除前已完成并校验的协作导出** |
| E | 可丢弃运行态 | 由服务管理，不作为项目事实 | 重新运行；不承诺复现未导出的在线状态或会话 |

“删库可恢复”对项目事实是完整承诺：同一来源包可重建同一逻辑事实。讨论、认领和数据库协作审计属于例外，必须事先导出；未导出数据不能从项目文件或 Agent 记忆补造。在线状态、未完成事务与短期会话是可丢弃状态，重启后重新建立。

第4轮已加入 governance.yaml、文件墓碑与协作导出格式。治理中的五个主体明确标记为本机验收账号，未接入真实团队或生产项目。以下实施补充由CHG-004记录；真实SQL与恢复结果待运行验收。

## 第4轮实施补充

- 实际业务表数为31：22张F/G、7张D、2张E；schema_migrations另属基础设施。手写迁移及逆迁移可重复执行，已应用迁移的SHA发生变化会拒绝继续。
- C表增加 `source_data jsonb NOT NULL`，权威G：完整保留共享解析器的规范化对象与额外源字段，避免仅映射显式列时丢失文件事实。缺少事实时间仍为null，不用同步运行时间补造。
- 全局主体只按tenant范围登记；project_owners必须在同tenant中有明确主体。禁止从原文owner显示名推断身份。稳定UUID基于tenant/project/kind/id，项目内同名对象由registry.kind区分。
- API与同步用独立非管理员LOGIN，分别继承无LOGIN的权限角色；API不能改F/G，sync只写F/G并更新E级sync_jobs。owner触发范围内同步；CLI默认全量，`--project`限定指定项目与对应tenant。
- 源删除时，无D引用对象从读模型移除；仍被D引用的对象必须在项目tombstones.yaml保留kind/id/deleted_at及完整原对象data。否则整次同步失败回滚，不在旧数据库中偷偷保留无源历史。迁移恢复要求完整文件与可用Git。
- `discussions.title`按现有创建契约原样保存首帖body，不由程序生成摘要；后续回复保存在discussion_posts.body。父回复外键包括discussion_pk，禁止同项目不同主题串帖。
- `last_export_id`与audit.export_id保留为空，不通过导出去更新不可变历史。API按已校验导出中的对象PK/revision推导export_status；导出本身不会改对象版本或F/G指纹。
- 七类D表在一条SQL查询的同一MVCC快照聚合，manifest列出data.json等文件的SHA。当前尚未完成的导出任务和账本排除于自己的快照，下一包包含已完成历史；本次完成回执由API另行保存。恢复承诺只覆盖manifest实际列出的完整数据集。
- 同步/导出先持久化任务和executing账本；同步角色把F/G更新与E发布标记同事务提交，API随后完成账本。文件导出用同一持久任务ID原子发布，回执失败后同键重试校验原包并接续，不假设数据库与文件系统共享事务。普通协作写入、revision、审计、幂等结果仍在一个API事务中提交。
- source roots支持CLI和环境变量指定多个目录。内部真实目录映射不序列化进网页；导出单独被读取，不能成为F/G投影输入。自动验收在仓库外目录已验证多根与冲突处理。

## 通用文件投影字段 C

下文所有标为“C”的文件投影表**实际都包含本表逐项字段**；表格后列出的只是该表专有字段。没有隐含数据库真源。租户全局表的 project_pk 可空，项目内对象必须非空。

| 字段 | PostgreSQL 逻辑类型 | 权威 | 规则与来源 |
|---|---|---|---|
| pk | uuid，PK | G | 用租户、项目、对象类型、稳定 id 的固定命名空间确定性生成；重建保持一致 |
| id | text，非空 | F | 文件中的稳定编号；无单独编号的关系行以两端 ID 确定性投影，不手工另造事实 |
| tenant_pk | uuid，FK tenants.pk | F | 来源包登记的租户归属；租户根对象自关联，不能信任客户端正文 |
| project_pk | uuid，FK projects.pk，可空 | F | 当前项目；全局租户/主体登记可空，其他表必须有项目范围 |
| owner_pk | uuid，FK principals.pk，可空 | F | 文件明确声明的所有者；缺失保持 null，不用 Agent 猜人 |
| created_at | timestamptz，可空 | F | 文件真实创建时间；旧文件没有则 null，不用本次导入时间冒充 |
| updated_at | timestamptz，可空 | F | 文件明确更新时间；保留原始时区并归一化，不能用数据库 now() 改历史 |
| deleted_at | timestamptz，可空 | F | 普通文件删除清单或墓碑的时间；没有证据不猜删除时间 |
| revision | text，非空 | G | 内容版本指纹，由规范化源内容散列生成；不冒称单调递增的业务版本号 |
| source_version | text，可空 | F | 文件显式业务版本，例如 v0.2；与内容指纹分开 |
| source_path | text，非空 | F | 来源包内相对文件路径，不允许跳出登记根目录 |
| source_pointer | text，非空 | G | 稳定对象 ID / JSON Pointer / 文档段落位置，能定位源文件 |
| source_sha256 | char(64)，非空 | G | 原始源文件字节哈希，重建与验收可复算 |
| source_commit_sha | text，可空 | G | Git 查询得到的真实 SHA；无版本历史或未提交时明确 null |
| source_actor_label | text，可空 | F/G | 优先明确的文件 actor 声明，否则可展示 Git 作者元数据并标来源；不等于已认证在线身份 |
| ingest_key | char(64)，非空 | G | 来源快照、对象稳定键和源哈希的散列；同快照重复导入不重复创建 |
| projection_epoch | text，非空 | G | 本次来源清单对应的投影快照标识，控制一次性发布 |
| projection_state | enum，非空 | G | staging / validated / published / stale / failed；只有 published 对外读取 |
| projection_version | text，非空 | G | 投影器与数据模型版本，明确同一文件由哪版算法计算 |

业务表逻辑唯一键为 `(tenant_pk, project_pk, object_type, id)`，具体表不含 object_type 时由表名承担。外键必须连同租户和项目范围检查，不能仅凭一个同名编号跨租户引用。主键算法是确定性数据处理，不承担语义判断。

导入审计不在每行重复保存真假混合的 before/after：来源单据的作者自述保留在 activity_records；Git 客观差异保留在 git_file_changes；真实在线事务的 actor、before、after 保留在 collaboration_audit_events。页面分别标注这三种来源。

## 通用数据库协作字段 D-COMMON

下文标为“D-COMMON”的持久协作表均包含以下字段，全部为 **D 数据库真源**，并进入导出清单；导出后可恢复这些值。它们不覆盖 C 表中的项目事实。

| 字段 | 类型与约束 | 权威 | 用途 |
|---|---|---|---|
| pk | uuid，PK | D | 创建时分配，导入导出保持稳定 |
| tenant_pk | uuid，FK tenants.pk | D | 从已验证身份与登记关系确定 |
| project_pk | uuid，FK projects.pk | D | 对应已授权项目，不允许悬空跨范围引用 |
| owner_pk | uuid，FK principals.pk | D | 该协作对象负责人；不改变项目文件的 owner |
| created_at | timestamptz，非空 | D | 事务创建时间 |
| updated_at | timestamptz，非空 | D | 最近成功修改时间 |
| deleted_at | timestamptz，可空 | D | 软删除，保留追溯；按权限隐藏正文 |
| revision | bigint，>=1 | D | 每次成功修改原子递增；携带旧版本则 409 |
| created_by | uuid，FK principals.pk | D | 服务从验证身份填写，不接受任意客户端 actor |
| updated_by | uuid，FK principals.pk | D | 最后一次已认证修改者 |
| idempotency_key | text，非空 | D | 关联 idempotency_requests；同操作重试不重复写入 |
| lifecycle_state | text，非空 | D | 各表定义合法中间态与终态，禁止未知字符串静默落库 |
| last_audit_pk | uuid，FK collaboration_audit_events.pk | D | 与业务修改同事务落审计；循环 FK 使用可延迟约束 |
| last_export_id | text，可空 | D | 保留字段；第4轮保持null，具体版本覆盖从已校验导出清单推导，不因导出反改历史 |

## 文件事实与客观派生表

每表均包含 C；下表逐项列出专有字段。`payload` 不能藏一套数据库独有事实，其逐类型字段在后节完整列明。

### tenants：租户登记（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| name | text | F | 未来治理登记文件的租户名称 |
| visibility_policy_ref | text | F | 文件中的可读权限策略引用，不包含秘密 |
| source_root_ref | text | F | 经维护者登记的来源根目录引用 |

### principals：主体登记（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| display_name | text | F | 人类/Agent 的登记显示名 |
| actor_type | enum human / agent / service | F | 主体类型 |
| identity_binding_ref | text，可空 | F | 外部认证绑定的非秘密引用；凭据只存秘密管理系统 |
| roles | text[] | F | 已审阅的登记角色，不能从讨论认领自动获得权限 |

### projects：项目（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| name | text | F | project.yaml.name |
| description | text | F | project.yaml.description |
| type | enum software / agent / aigc | F | project.yaml.type |
| kind | text | F | web / service 等类型内说明 |
| example | boolean | F | 明确真实与虚构，不能从名称推断 |
| stage | text | F | 文件声明的当前阶段 |
| focus_requirement_pk | uuid，FK requirements.pk，可空 | F | 关注需求引用 |
| onboarding | jsonb | F | onboarding.yaml 六段；环境仅存 server_ref，地址仍来自 OpenAPI |

### repositories：登记仓库（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| local_path | text | F | project.yaml / 变更单 repo 指向的登记本地路径 |
| remote_url | text，可空 | F | 文件中的仓库链接；无远端保持空 |
| branch | text，可空 | F | project.yaml 中的分支说明 |
| availability | enum reachable / unavailable | G | 本次 Git 读取结果 |
| unavailable_reason | text，可空 | G | 工具真实返回的脱敏失败原因，不用摘要遮盖 |

### requirements：需求（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| title | text | F | 需求 frontmatter |
| original | text | F | 用户原话正文，原文保留 |
| understanding | text | F | 当前理解正文，与原话分开 |
| provenance | text | F | 来源说明及未核实范围 |
| status | text | F | 需求状态 |
| priority | text | F | 文件优先级 |
| next_action | text | F | 文件下一步，不从在线认领自动修改 |
| steps | jsonb array | F | 各环节阶段，类型不适用项明确表达 |

### requirement_checks：验收条件（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| requirement_pk | uuid，FK requirements.pk | F | 所属需求 |
| position | integer，>=0 | G | 文件中顺序；与稳定父对象共同定位 |
| text | text | F | 验收条件原文 |
| checked | boolean | F | 文件中真实标记，不由测试数量推断 |

### changes：变更单（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| title | text | F | changes/*.md.title |
| narrative | text | F | 作者自述正文，必须显示来源标签 |
| status | text | F | 进行中、已提交或无历史等声明 |
| round | integer，可空 | F | 明确的轮次 |
| history_note | text，可空 | F | 无版本历史等来源边界 |
| repository_pk | uuid，FK repositories.pk | F | 变更单 repo 登记引用 |

### change_requirements：变更关联需求（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| change_pk | uuid，FK changes.pk | F | 变更单对象 |
| requirement_pk | uuid，FK requirements.pk | F | frontmatter.reqs 每个引用 |

唯一约束 `(change_pk, requirement_pk)`。不根据 diff 关键词自动新增需求关系。

### change_commits：变更关联提交（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| change_pk | uuid，FK changes.pk | F | 变更单对象 |
| repository_pk | uuid，FK repositories.pk | F | 变更单登记仓库 |
| declared_commit_sha | text | F | commit 字符串/数组，不伪造缺失值 |
| git_commit_pk | uuid，FK git_commits.pk，可空 | G | 成功解析后关联；不可达不伪造实体 |
| resolution_status | enum resolved / unavailable / missing | G | 真实提取结果 |
| resolution_reason | text，可空 | G | 明确失败原因 |

### git_commits：Git 提交事实（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| repository_pk | uuid，FK repositories.pk | F | 登记仓库 |
| sha | text，仓库内唯一 | G | git rev-parse / log 验证值 |
| parent_shas | text[] | G | 提交父节点；根提交为空 |
| author_label | text | G | Git 作者元数据，不等于在线认证主体 |
| authored_at | timestamptz | G | Git 作者时间，不能替换为导入时间 |
| committed_at | timestamptz | G | Git 提交时间 |
| subject | text | G | Git 提交标题，保留原样 |
| file_count | integer | G | Git 文件清单客观计数 |
| insertions | integer，可空 | G | 文本增加行；二进制未知为 null |
| deletions | integer，可空 | G | 文本删除行；二进制未知为 null |

### git_file_changes：Git 文件与原始 diff（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| git_commit_pk | uuid，FK git_commits.pk | G | 已验证提交 |
| old_path | text，可空 | G | Git old path；新增为空 |
| new_path | text，可空 | G | Git new path；删除为空 |
| change_kind | enum added / modified / deleted / renamed / copied / binary | G | Git 状态输出 |
| added_lines | integer，可空 | G | Git numstat |
| deleted_lines | integer，可空 | G | Git numstat |
| patch | text | G | 原始 patch，不能由 Agent 改写 |
| hunks | jsonb | G | 从 patch 确定性解析的 old_start / old_count / new_start / new_count / lines |
| before_blob_sha | text，可空 | G | Git before blob |
| after_blob_sha | text，可空 | G | Git after blob |
| patch_truncated | boolean | G | 是否截断；展示必须声明，不能把部分补丁当完整 diff |
| patch_bytes_total | bigint，可空 | G | 原补丁总字节数；读取失败保持未知 |
| patch_bytes_kept | bigint | G | 实际保留的补丁字节数 |
| extraction_status | enum available / partial / unavailable / no_history | G | 提取状态，页面不得静默省略失败 |

“新增/修改/删除几个文件、增删几行”可由这些字段形成确定性人话摘要；“为什么改、效果如何”仍属于作者自述或实际验收，不能从行数推断。

### test_cases：测试与验收（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| title | text | F | 测试单标题 |
| requirement_pk | uuid，FK requirements.pk | F | req 引用 |
| environment_ref | text | F | 测试单环境，包括不适用/本地 |
| expected | text | F | 预期 |
| actual | text | F | 实际回执或明确尚未执行 |
| result | text | F | 真实结果，历史回执与本轮重测分开 |
| record_pk | uuid，FK activity_records.pk，可空 | F | 关联记录 |

### releases：发布（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| title | text | F | 发布单标题 |
| status | enum planned / deploying / verifying / released / failed / rolled_back | F | 文件记录的发布中间态与结果 |
| version_label | text | F | 发布版本 |
| environment_ref | text | F | 环境引用，URL 不在本表另手写 |
| change_ids | text[] | F | 来源变更 ID；写入时校验 FK 对应对象 |
| test_ids | text[] | F | 依据测试 ID；写入时校验对应对象 |
| receipt_ref | text，可空 | F | 实际发布回执文件；没有则不可宣称 released |
| rollback_notes | text | F | 回退步骤与数据兼容边界 |

### incidents：事故（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| title | text | F | 事故单标题 |
| status | enum open / investigating / mitigated / resolved | F | 事故状态 |
| severity | text | F | 有依据的级别 |
| symptom | text | F | 固定症状 |
| expected | text | F | 预期行为 |
| evidence_refs | text[] | F | 实际证据文件 |
| cause | text，可空 | F | 已确认原因；未知保持空 |
| resolution | text，可空 | F | 真实处理与回执 |

### security_audits：安全审计单（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| title | text | F | 安全审计单标题 |
| status | enum planned / reviewing / completed | F | 审计状态；未执行不填 completed |
| scope | text | F | 审计对象和范围 |
| findings | jsonb array | F | 发现、证据、影响与处理状态 |
| auditor_label | text | F | 执行者声明与来源 |
| evidence_refs | text[] | F | 可读取证据引用；不放凭据值 |

### retrospectives：复盘（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| title | text | F | 复盘标题 |
| status | text | F | 当前状态 |
| observations | text | F | 观察事实及来源 |
| interpretations | text | F | 作者解释，不能冒充客观事实 |
| decisions | text | F | 明确决策 |
| followup_requirement_ids | text[] | F | 跟进需求，存在性校验 |

发布、事故、审计、复盘的通用 reqs 关系均落入 object_links，并校验目标需求；空目录代表没有对应真实单据，不补造数据库行。

### activity_records：过程记录（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| title | text | F | 记录标题 |
| stage | text | F | 产品、UI、前端、后端、测试、运维、审计等 |
| environment_ref | text | F | 记录环境 |
| actor_label | text | F | 记录作者声明的操作者，不等于服务认证身份 |
| detail | text | F | 正文 |
| before_description | text | F | 作者记录的变化前描述 |
| after_description | text | F | 作者记录的变化后描述 |
| result | text | F | 记录结果 |
| target_ref | text | F | 可解析的相关产物引用 |

### api_contracts：完整接口契约（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| openapi_version | text | F | api/openapi.json 或 YAML |
| title | text | F | info.title |
| contract_version | text | F | info.version |
| document | jsonb | F | 完整标准契约，包括 schemas、servers、examples、security 与 extensions |
| validation_profile | text | G | 校验器与支持范围说明，不等于业务验证 |

### environments：环境（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| contract_pk | uuid，FK api_contracts.pk | F | 所属契约 |
| server_ref | text，项目内唯一 | F | servers[].x-environment |
| label | text | F | server.description / onboarding 标签 |
| base_url | text | F | 只从 OpenAPI servers[].url 派生 |
| deployment_state | text | F | 明确的文件部署状态；设计地址不得推断在线 |

没有 API 的 agent/aigc 项目可没有环境行；渠道配置属于主数据，不能伪装成软件 API 环境。

### master_objects：按类型的主数据（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| project_type | enum software / agent / aigc | F | project.yaml.type |
| object_type | text | F | 下节列明的类型内对象类别 |
| title | text | F | 对象标题 |
| status | text | F | 明确状态 |
| payload | jsonb | F | 仅含下节列明的类型字段，按对应文件 schema 校验 |

采用共同对象表与受约束的 profile payload，避免每新增一个类型就复制全部单据表。稳定 ID、关系、搜索与 diff 共用；语义不同的 payload 分别校验，不允许任意 JSON 代替字段契约。未来查询压力证实有必要时可以增加派生专表，原文件权威不改变。

### object_links：通用关系（C）

| 字段 | 类型/约束 | 权威 | 来源 |
|---|---|---|---|
| from_pk | uuid | F | 来源对象稳定键；同步时验证所属表对象存在 |
| from_kind | text | F | 来源表/对象类别 |
| relation | enum requirement / screen / field / api / test / change / source | F | 文件中明确的关系类别 |
| to_pk | uuid | F | 目标对象稳定键 |
| to_kind | text | F | 目标表/对象类别 |

多态外键不可用单列普通 FK 充分约束。实现阶段需以统一对象注册表加真实 FK，或逐类别关系表兑现数据库约束；不能只写“有 FK”却靠不存在的数据库机制。本文选择统一 `object_registry`，也包含完整 C 通用字段（遵循 C 的逐字段权威，值来自已注册源对象），专有字段只有 `kind text`（G，对象所属类别）。PK=pk、唯一键为租户/项目/类别/id，from_pk/to_pk 外键均指向它。每个 C 对象与 registry 的同 PK 行在一个发布事务内创建或移除；registry 不成为另一份可编辑事实。

## 主数据 payload 逐字段权威

以下字段注明 F 的由文件直接提供，注明 G 的为只读派生；未单列标记者为 F。新增 profile 候选字段的来源映射须在实现时明确，不冒充当前文件已经具有的字段。没有列出的字段不得悄悄成为数据库独有事实。

| 项目类型/对象类型 | payload 字段 | 每项来源与含义 |
|---|---|---|
| software / screen | route、purpose、status、fields（F）；apis（G） | 前四项来自页面文件；apis 从 OpenAPI 的 x-screens 反向派生，不在页面文件重复维护；reqs 单独投影到关系表 |
| software / field | name、type、entity、origin、required、rule、reason（F）；screens、apis（G） | 前七项来自字段文件；screens 从页面 fields、apis 从 OpenAPI x-fields 反向派生，不在字段文件重复维护 |
| software / api_operation | operation_id、method、path、summary、description、tags、parameters、request_body、responses、security | 全部从同一个 OpenAPI 文档的 operation 投影；examples 保持原对象，不另手写副本 |
| software / prototype | kind、demo_date、tasks | 纯演示原型来源；不当作实际业务任务或项目事实的数据库记录 |
| agent / prompt_segment | segment_id、order、text、purpose、scope、status | 每段提示词有稳定 segment_id 与独立可定位正文；重排不改编号，删除保留墓碑与 Git 历史 |
| agent / tool | tool_id、name、description、input_schema、output_schema、permission_ref、side_effects | 工具能力与边界来自文件；工具实际运行回执不是本行自述 |
| agent / memory_policy | policy_id、scope、write_rules、retrieval_rules、retention、visibility | 记忆策略文本及范围，不引入真实私密记忆内容 |
| agent / channel_model | config_id、channel、model、routing_notes、credential_ref、status | 渠道与模型配置候选；credential_ref 只能是登记引用，不能保存值 |
| agent / permission_boundary | boundary_id、subject_ref、resource_scope、allowed_actions、denied_actions、approval_notes | 明确授权范围，不能从人格提示词推断权限 |
| aigc / work | work_id、title、synopsis、format、status | 作品层次与定位 |
| aigc / unit | unit_id、parent_id、unit_type、order、outline、content_ref、status | 集/章/镜头稳定编号与父子关系，parent_id 校验同作品范围 |
| aigc / prompt | prompt_id、unit_refs、text、model_notes、parameters、status | 生成提示词及关联单元；不将提示词当真实产出 |
| aigc / asset | asset_id、unit_refs、local_path、source_url、sha256、media_type、rights_notes、status | 素材位置、来源、校验值与权利说明；远程地址存在不等于已保留素材本体 |
| aigc / style | style_id、name、description、reference_asset_ids、constraints | 风格说明与引用；引用需存在 |

这些 profile 字段是数据库设计候选，主任务当前示例采用的具体文件形状由文件模型文档说明。字段名称需要映射时应在投影器中明确记录和校验；不得改写原文件含义或强行给 agent/aigc 添加前端、后端页面。

## 数据库协作真源表

### discussions：讨论主题（D-COMMON）

| 字段 | 类型/约束 | 权威 | 用途 |
|---|---|---|---|
| target_pk | uuid，FK object_registry.pk | D | 讨论关联的已存在项目对象 |
| title | text | D | 协作主题 |
| resolved_at | timestamptz，可空 | D | 讨论结束时间，不直接改变需求状态 |

lifecycle_state：open → resolving → resolved，可重新打开。导出为含稳定 ID、版本、作者和时间的 Markdown。

### discussion_posts：讨论回复（D-COMMON）

| 字段 | 类型/约束 | 权威 | 用途 |
|---|---|---|---|
| discussion_pk | uuid，FK discussions.pk | D | 所属主题 |
| parent_post_pk | uuid，FK discussion_posts.pk，可空 | D | 回复关系，同讨论范围 |
| body | text | D | 正文，禁止保存秘密 |
| edited_at | timestamptz，可空 | D | 编辑时间；改动前后进入协作审计 |

lifecycle_state：draft → posted → redacted。软删除保留必要审计，脱敏或删除正文的权利和保留期需单独定义，不能以“审计”无限保留敏感内容。

### claims：临时认领（D-COMMON）

| 字段 | 类型/约束 | 权威 | 用途 |
|---|---|---|---|
| target_pk | uuid，FK object_registry.pk | D | 被认领对象 |
| claimant_pk | uuid，FK principals.pk | D | 已授权认领主体 |
| expires_at | timestamptz，可空 | D | 可选租约截止 |
| released_at | timestamptz，可空 | D | 主动撤回/释放时间 |

lifecycle_state：pending → active → releasing → released，或 active → expired。对同租户/项目/目标的 active 认领使用部分唯一约束，具体允许多人还是单人需由下一轮产品毛坯确认。认领不能更改项目 owner 或授予新权限。

### notifications：通知（D-COMMON）

| 字段 | 类型/约束 | 权威 | 用途 |
|---|---|---|---|
| recipient_pk | uuid，FK principals.pk | D | 接收者 |
| cause_audit_pk | uuid，FK collaboration_audit_events.pk，可空 | D | 引发通知的动作 |
| payload | jsonb | D | 最小必要信息与对象引用，不复制秘密或全部讨论正文 |
| delivered_at | timestamptz，可空 | D | 真实送达回执时间 |
| read_at | timestamptz，可空 | D | 真实阅读状态 |

lifecycle_state：queued → sending → delivered → read，失败为 failed；重试不能把 accepted 当 delivered。导出可选择保留阅读状态，但它不影响项目事实恢复。

### idempotency_requests：幂等请求账本（D-COMMON）

| 字段 | 类型/约束 | 权威 | 用途 |
|---|---|---|---|
| actor_pk | uuid，FK principals.pk | D | 请求主体 |
| operation | text | D | API 操作命名空间 |
| request_sha256 | char(64) | D | 脱敏后规范化业务输入摘要，不包括凭据 |
| response_status | integer，可空 | D | 已完成请求的响应状态 |
| response_body | jsonb，可空 | D | 可安全复用的结果或结果引用；不缓存登录 token |
| expires_at | timestamptz | D | 幂等保留期，需在实现契约里确定 |

唯一键 `(tenant_pk, actor_pk, operation, idempotency_key)`。lifecycle_state：reserved → executing → completed / failed。并发相同键只允许一个执行者；相同键不同摘要返回 409。超过期限不能未经说明仍声称永久去重。恢复协作历史时可导入未过期的 completed 条目；executing 条目恢复为需核对，不盲重放副作用。

### collaboration_audit_events：真实在线动作审计（专用 D 表）

该表是不可变事件，避免用更新覆写审计；不继承可变 D-COMMON。以下为全部字段。

| 字段 | 类型/约束 | 权威 | 用途 |
|---|---|---|---|
| pk | uuid，PK | D | 事件稳定编号 |
| tenant_pk | uuid，FK tenants.pk | D | 租户 |
| project_pk | uuid，FK projects.pk | D | 项目 |
| owner_pk | uuid，FK principals.pk | D | 审计责任归属，来自当次授权上下文 |
| actor_pk | uuid，FK principals.pk | D | 已认证实际主体 |
| actor_type | enum human / agent / service | D | 当次主体类别 |
| action | text | D | 实际动作 |
| target_kind | text | D | 被改协作对象类别 |
| discussion_pk | uuid，FK discussions.pk，可空 | D | 主题目标，按 target_kind 选择 |
| post_pk | uuid，FK discussion_posts.pk，可空 | D | 回复目标，按 target_kind 选择 |
| claim_pk | uuid，FK claims.pk，可空 | D | 认领目标，按 target_kind 选择 |
| notification_pk | uuid，FK notifications.pk，可空 | D | 通知目标，按 target_kind 选择 |
| idempotency_request_pk | uuid，FK idempotency_requests.pk，可空 | D | 请求账本目标；对尚未创建对象的拒绝事件可以为空 |
| before_value | jsonb，可空 | D | 动作前脱敏快照；创建为 null |
| after_value | jsonb，可空 | D | 动作后脱敏快照；删除保留必要墓碑 |
| expected_revision | bigint，可空 | D | 请求读取版本 |
| resulting_revision | bigint，可空 | D | 事务成功后的版本，失败不冒增 |
| idempotency_key | text | D | 与请求账本对应 |
| request_id | text | D | 请求关联编号 |
| result | enum accepted / succeeded / rejected / failed | D | 当次真实结果，accepted 不当终态成功 |
| reason_code | text，可空 | D | 可读原因枚举引用 |
| created_at | timestamptz | D | 事件实际发生时间 |
| updated_at | timestamptz | D | 等于 created_at；不可变事件不更新 |
| deleted_at | timestamptz，可空 | D | 依法/授权处理时的墓碑时间；正文脱敏需新增说明事件，规则待实现确认 |
| revision | integer，固定1 | D | 单条事件不可变版本 |
| export_id | text，可空 | D | 最近已校验导出清单 |

目标外键按 target_kind 做 CHECK：成功修改事件必须且只能选中一个对应对象；在对象尚不存在时发生的拒绝/失败可全部为空，并保留 request_id 与原因。这样使用真实外键，不假设 PostgreSQL 存在多态 FK。协作修改、revision 增量、幂等结果与对应审计在一个数据库事务中提交。对实际身份的断言只来自未来认证执行链，不能用 Agent 自述或 Git author 替代。

## 可丢弃运行表与导出收据

### sync_jobs：同步运行态（E）

全部字段为 E：`pk uuid PK`、`tenant_pk FK`、`project_pk FK`、`owner_pk FK`、`created_at timestamptz`、`updated_at timestamptz`、`deleted_at nullable`、`revision bigint`、`idempotency_key text`、`actor_pk FK`、`source_snapshot text`、`previous_snapshot text nullable`、`state enum queued/validating/staging/published/failed`、`error jsonb nullable`、`published_snapshot text nullable`。这些字段记录运行状态，不能代替已发布项目事实；删库后从完整来源快照重新执行，不能伪造上次未保留运行历史。

### presence：在线状态（E）

全部字段为 E：`pk uuid PK`、`tenant_pk FK`、`project_pk FK`、`owner_pk/actor_pk FK`、`created_at`、`updated_at`、`deleted_at nullable`、`revision bigint`、`idempotency_key text`、`state enum online/idle/offline`、`last_seen_at`、`expires_at`。短 TTL，数据库丢失后显示未知/离线，等待新心跳；不导出成“历史在线事实”。短期会话 token 不进入上述表或导出，恢复后重新认证。

### collaboration_exports：导出任务（D，完成后可从文件清单重建）

全部字段逐项权威：`pk uuid PK` D、`tenant_pk FK` D、`project_pk FK` D、`owner_pk/actor_pk FK` D、`created_at/updated_at/deleted_at` D、`revision bigint` D、`idempotency_key text` D、`state queued/running/completed/failed` D、`requested_scopes text[]` D、`high_watermark text nullable` D、`manifest_path text nullable` D、`sha256 text nullable` D、`error_code text nullable` D、`before_state/after_state text` D。已完成任务的全部字段进入下一次导出的历史快照；本次任务不包含自身完成收据，避免自身sha256循环。未完成任务没有可恢复保证。

## 系统字段逐项对照

| 要求 | 文件事实层 | 协作事务层 |
|---|---|---|
| 主键与外键 | C.pk、registry 与按租户/项目检查的关联 | UUID 主键、同范围 FK 与唯一约束 |
| created_at / updated_at | 文件实有时间，缺失 null，禁止导入时捏造 | 数据库事务真实时间，导出原值 |
| 软删除 | 文件墓碑/删除清单；Git 可追溯 | deleted_at + 必要墓碑，按权限隐藏 |
| 版本 | 源业务版本 + 内容指纹 + 投影版本 | revision 原子递增，冲突 409 |
| 所有者与租户 | 文件明确登记；缺失不猜 | 认证上下文与授权关系，认领不授予权限 |
| 幂等 | ingest_key 避免同快照重复导入 | 唯一幂等账本与请求摘要 |
| 中间态 | staging → validated → published，失败保留旧快照 | 各协作对象、导出、通知与同步有明确状态机 |
| 谁改了 | 作者声明与 Git 元数据分开标注 | 已认证 actor + request_id |
| 从什么改成什么 | 作者 before/after 与 Git 原始 diff 分开 | 同事务脱敏 before_value/after_value |

## 未来从文件完整重建的步骤

本轮只有此设计，没有实现数据库重建命令。现有 `python build.py` 仍只需要当前文件与已装构建依赖，正常生成离线站。

1. **准备来源包**：项目 Markdown/YAML/OpenAPI、已登记租户/主体引用、删除墓碑清单、必要素材清单、模型版本以及需要提取 diff 的 Git 对象。源根和 Git 缺失必须报告，不由 Agent 补历史。
2. **文件验证**：按现有规则解析、校验 OpenAPI 和所有对象关系；错误报告具体文件与行号。产生确定性清单与各文件 SHA-256。
3. **创建空投影区**：先完成未来数据库结构迁移，再将租户、主体、项目、registry 与各类事实写入 staging，使用稳定主键和 ingest_key。
4. **提取 Git 事实**：按变更单真实 repo+commit 读取；不可达保留 unavailable。没有原 Git 对象不能恢复原始 diff，该缺口必须呈现在站点。
5. **完整性比对**：校验每类对象数、ID、引用、规范化内容哈希、软删除与来源清单；数据库事实必须与文件投影相同。
6. **原子发布**：事务切换 published 快照，失败保留旧快照。重复执行同一来源包得到相同逻辑数据，运行任务时间可以不同且不污染事实。
7. **恢复协作例外**：只有存在删除前完成且哈希校验通过的导出包，才按稳定 ID、revision、时间、作者与引用恢复 discussions/posts/claims/audit。没有导出时明确这些数据已不可恢复，不从需求、日志或模型记忆重写。
8. **独立验收**：无数据库时离线站仍能阅读同一项目事实；有数据库时按对象和哈希比较。协作恢复另行检查导出高水位，报告遗漏范围，不能以项目数一致代替协作恢复通过。

## 协作导出设计

导出路径在未来项目来源包的 `collaboration-exports/<export-id>/`，包含可读 Markdown 回复、YAML 认领、脱敏审计 JSON 和 `manifest.json`。使用普通格式，不绑定 Agent 私有记忆服务。

在一致性快照上固定 high_watermark，记录各对象稳定 ID/revision、时间、作者、目标引用和 SHA-256；先写临时目录，全部校验后原子发布完成清单。完成之前 API 状态仅 running，失败不覆盖上次完整包。导出不得含密码、签名密钥或有效 token；凭据只保留登记 ID。

文件已导出也不自动晋升为需求或产品事实。把讨论结论采用为正式需求时，必须通过人类可见的文件变更与 Git 提交完成，并关联来源讨论导出 ID。数据库导出频率、保留期、删除与脱敏规则及真实恢复演练留待下一轮设计验收后实现。
