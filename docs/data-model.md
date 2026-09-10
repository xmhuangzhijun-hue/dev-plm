# 项目文件与构建视图

文件采用 Markdown + YAML frontmatter、YAML、OpenAPI JSON。以下是本项目约定的数据字段，不把它们称为通用 PLM 标准。

## 唯一维护入口

| 文件 | 职责 |
|---|---|
| `project.yaml` | id、名称、定位、kind、example、状态、更新时间、repo、branch、local_path、focus_requirement |
| `onboarding.yaml` | frontend / backend 的运行说明、database、configuration、environments、owners |
| `requirements/*.md` | 需求元信息与当前状态、七阶段 steps、checks；正文保存用户原话与当前理解 |
| `ui/screens.yaml` | 页面 id、路由、用途及其需求/字段引用；接口列表从契约生成 |
| `ui/prototype.yaml` | 可操作毛坯的初始示例数据；页面操作不会写回该文件 |
| `data/fields.yaml` | 字段含义、候选类型、约束、归属与关联 |
| `api/openapi.json` | 标准契约，包括环境、认证、示例与错误码 |
| `records/*.md` | 环节、环境、关联需求、操作者、前后值、结果、目标产物；正文解释变化 |
| `tests/*.md` | 来源需求、预期、结果、环境与对应过程记录 |

目录内其他 Markdown/YAML/JSON 文件也收录到资料目录。README 等叙述文件不必有 frontmatter。

需求视图的页面、字段和接口列表由相关对象的 `reqs` / `x-requirements` 反向推导，不在需求文件中再维护一份。文件查看器展示的文本由构建时读取，接口示例由标准 `examples` 投影。`project-data.js` 只有生成版本，不存在手工维护的平行数据表。

API 与页面、字段的关系只在 OpenAPI `x-screens` / `x-fields` 维护；页面与字段的关系只在 `ui/screens.yaml` 的 `fields` 维护。字段页的接口/页面列表与页面上的调用接口列表由构建反推，不要求人同时修改两个方向的关联。

## 标识与引用

项目 id 与目录名一致。各项目的 ID 在自身作用域内解析，不把同名对象跨项目混在一起。接口 ID 使用 operationId。记录的 `target` 指向站内对象，例如 `#apis/createTask` 或 `#files/onboarding.yaml`。parent 可指向同项目的既有单据。

前端页与后端页读取相同项目级仓库信息。将来如果采用分仓，可在形态确认后扩展代码组件清单，不需要为了演示而伪造多个仓库。

## 原话的 Markdown 写法

```markdown
## 用户原话

> 我希望保留下面这一段。
> ## 这是原话里的标题
> 这行仍然是原话。

## 当前理解

这里单独描述当前理解。
```

构建将原话引用块的一个 `>` 层级还原。这样原话本身含二级标题也不会截断；导出草稿使用相同约定。

## 构建事务

先读取并验证全部源文件，再写入 `.work/site-stage/`。全部完成后替换 `site/`；替换失败会恢复上一版。坏引用不会更新现有网页。生成目录的操作在执行前检查绝对路径属于本仓库的生成区域。

源文件摘要展示于网页底部，便于确认当前视图对应哪个文件版本；它不是生产状态或审计签名。


## 第3轮增量

project.yaml 必填 type: software / agent / aigc。仅 id=dev-plm 可 example=false；四个样例为true。software保留第2轮主数据校验；其他type使用profile.yaml，免除onboarding/ui/api要求。

通用changes、releases、incidents、audits、reviews中Markdown frontmatter必填id、title、reqs、status；changes另必填repo、commit。引用错误继续报源文件行号。记录target接受changes/profile/impact/design/code和共用单据，按对象ID校验。无法提取Git是资料缺失状态，不是引用错误，不阻断构建。

profile.groups按type指定分组，每组含id/title/objects。对象id在profile内唯一。Agent prompt通过file读取稳定id/title/reqs和正文，禁止在profile再维护内容。可选git_path须为目标Git根内相对文件；对应history_repo或git_repo指定仓库。AIGC对象source也会验证必须位于本项目且存在。

project.yaml 可选code_entries列表(id/title/path)直接读取工作台仓库内源码，生成只读源码入口。代码不能指向隐藏目录、仓库外路径或不在白名单的文件类型。复制生成页面不是新的维护入口。

build.sourceSha256覆盖项目文件及登记的源码，build.gitSha256覆盖Git提取结果。所有数据每次从真源构建，site没有手工数据。Git事实不等于作者对改动动机的解释；需求与变更的关联是作者登记，不能宣称自动证明因果关系。
