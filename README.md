# dev-plm

把应用开发过程变成人能查看的项目工作台：需求、UI、字段、API、开发、测试、运维、审计和全过程日志。

普通文件与文件夹保留为资料来源。Agent照常记录工程工作，网页直接呈现已授权的日志，不要求使用者重复录入或手动同步。

## 已有能力

- 离线资料站：从Markdown、YAML和OpenAPI构建静态网页，包含需求关联、版本变更及虚构交互样例。
- 私有在线工作台：FastAPI与原生JavaScript，提供文档编辑、讨论、回复、认领及操作记录；PostgreSQL保存协作数据。
- 实时工程日志：按项目、环节、环境和关键词查看；页面前台每15秒检查更新，原文按需读取。
- 完整项目导航：总览、需求、UI、字段、API、开发、测试、运维、审计、全过程日志。登记的原文直接读取，缺失资料明确说明。
- 权限与边界：日志来源按租户和具体账号授权；私有目录、凭据、数据库、协作记录不包含在公开包中。

## 运行离线版

使用Python 3.10或更新版本，在隔离环境中准备 requirements.txt 的依赖，然后执行：

```sh
git clone fixtures/agent-demo.bundle .work/agent-demo-history
python build.py --public --data-root projects
python tools/check_publish_safety.py site/
```

用浏览器打开 site/index.html。离线版无需登录、数据库或网络连接。示例Git bundle仅包含虚构历史，恢复操作只需执行一次。

## 私有在线版

在线版是目前面向Windows本机、PostgreSQL和私有HTTPS环境的实现，尚不是一键托管服务。在线依赖单独列在 backend/requirements.txt。先阅读 .env.example、docker-compose.yml、backend/config.py 与 tools/local_stack.py，自行准备数据库、账号绑定和HTTPS入口。认证适配器使用本机登记的秘密引用，不提供默认密码。

可用界面是原生HTML/CSS/JavaScript，不需要React。资料写入与协作操作经后端权限和版本校验；离线站保持独立。

外部工程日志在私有 .local/log-sources.json 中登记来源与允许读取的账号：

```json
{
  "sources": [{
    "id": "my-project",
    "name": "My project",
    "directory": "../private-projects/my-project/logs",
    "readers": [{"tenant_id": "my-tenant", "principal_id": "my-reader"}],
    "sections": {
      "overview": {
        "note": "项目说明",
        "documents": [{"title": "README", "path": "../my-project/README.md"}]
      }
    }
  }]
}
```

这些是配置示例，不会创建账号或自动授予访问权限。外部日志支持带frontmatter的Markdown工程记录。目录和读者须由部署者明确登记；不要将这份私有配置提交到Git。

## 开发与验证

```sh
python -m pytest tests/test_live_logs.py tests/test_external_logs.py tests/test_project_documents.py tests/test_private_gateway.py
```

数据库测试需要独立测试环境。不要针对正在使用的数据库执行恢复演练。维护和备份工具仍属实验功能，需要显式配置；不会因运行网页自动安装计划任务。

## 公开内容

本仓包含系统源码、测试、四个虚构样例和经过筛选的自举资料。未包含原本机Git历史、真实业务资料或生产验收记录。自举资料引用的旧提交可能在本仓不可读取，界面会说明，不补造历史。

静态网页发布流程是手动触发的GitHub Actions；开源源码并不自动启用Pages。公开构建必须指定本仓projects，不得发布合并了私有目录的产物。详见 [发布边界](docs/publication.md)。

## License

MIT，见 [LICENSE](LICENSE)。第三方Schema保留原许可，见 vendor/openapi/licenses/。

Pages工作流示例位于 docs/pages-workflow.example.yml。需要部署静态站时，自行将其放入 .github/workflows/pages.yml 并配置Pages。本次只发布源码。
