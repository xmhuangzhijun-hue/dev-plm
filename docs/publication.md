# 当前源码导出说明

以下保留公开构建及公私分离设计。当前代码已包含私有在线工作台、实时日志及完整项目导航；旧文中后端未验收或未来前端的描述属于历史。公开副本不附带任何实际私有来源配置或账号。

# 公私分离与手动发布

## 边界与目录

公开内容是系统代码、构建测试、公开说明、四个虚构样例和dev-plm自举数据。私有项目及其截图、缓存、导出、日志、凭据永远留在仓库外。真实数据接入仍需另行授权，本轮只使用仓库外临时虚构资料验证。

代码仓库projects/只放公开内容；私有根可以是相邻private-projects/，其中每个项目仍按project.yaml、requirements/等普通目录组织。CLI重复 `--data-root` 优先于环境变量DEVPLM_DATA_ROOTS（Windows分号分隔）。相同项目ID不会覆盖，而是带位置报错。

```sh
# 公开版：忽略环境里可能存在的私有根，仅接受此仓库projects目录。
python build.py --public --data-root projects
python tools/check_publish_safety.py site/
# 本地合并版：不执行公开模式，不得用于发布。
python build.py --data-root projects --data-root ../private-projects
```

合并后必须重新公开构建才能发布。检查器要求public清单与实际项目集合匹配；缺少清单、未知项目、协作导出、无法检查的文件、损坏策略都失败。公开构建先在临时区完成检查，再替换site；失败不覆盖之前可用网页，但命令返回非零，工作流不会沿用旧产物继续发布。

## 检查覆盖与白名单

检查器逐文件读取实际字节，报告相对文件名、物理行号、类别与片段；包括路径、邮箱、数字凭据登记编号、常见长密钥形态、身份字段。JSON转义、Unicode转义、HTML实体及百分号编码先规范化再检查。匹配密钥形态时片段被遮蔽，避免诊断本身泄露真实值。

publication-policy.json中的白名单仅允许完整文字、精确文件、精确类别和理由；不能使用正则通配放行。虚构身份是完整值清单；未知author/owner/username等身份字段拒绝。唯一二进制样例bundle采用已人工核对的精确SHA白名单，变动必须重新审阅；其他二进制默认拒绝。

本机还可提供**仓库外**JSON清单（identities、roots、project_ids三个字符串列表），精确检查已知私人姓名、用户名、私有根和项目编号；该清单不会复制进网页或公开包。`--private-data-root`可直接读取该根下project.yaml中的项目ID并禁止它们进入公开产物。

```sh
python tools/check_publish_safety.py site/ --private-inventory ../private-publish-inventory.json --private-data-root ../private-projects
```

规则检查无法自动判断任意自然语言是否包含未登记的私人姓名或事实。因此发布前仍需用户审阅完整公开快照和站点，补齐私人身份清单；通过检查只表示规则、范围和已提供清单未命中，不是对所有语义隐私的数学证明。不要为了通过检查，把真实私人姓名加进虚构身份白名单。

## 历史的保存方式

CHG-001仍保留第1轮无Git历史的事实，目录改为不披露本机位置的说明。其他自举仓库路径改为相对路径。原本机Git历史没有删除、重写或推送。

公开模式只裁剪自举项目Git派生的身份、原提交说明和历史补丁；保留真实SHA、日期、文件名、增删统计，并明确标记省略。普通本地构建仍能查看完整Git历史。新写项目正文或源码不被静默脱敏，注入敏感内容必须失败。

**不要直接把原仓库添加公开remote后推送**：旧提交、旧生成物和私人作者信息仍在原历史中。使用下面的干净导出工具，它只复制精确允许的代码/项目集合，不复制.git、site、旧工程日志、协作导出、缓存和真实私有项目。backend文件按原字节复制，本轮不修改后端。

```sh
python tools/prepare_public_repo.py ../dev-plm-public-review
```

目标必须是仓库外的新目录，已有目标会失败，不覆盖。PUBLIC_EXPORT.json记录每份文件SHA、项目集合及未发布状态。可复制到其他位置重新运行；工具不创建GitHub仓库、不初始化公开仓库、不push。

## 用户执行的发布步骤

1. 审阅干净目录与PUBLIC_EXPORT.json，在该目录准备依赖并恢复虚构bundle、构建公开站、跑检查器。不要把原.git目录复制进去。
2. 用户选择适合代码的许可证，并用自己的对外账号初始化新的本地历史、创建公开仓库、提交和推送。工具没有代为执行这些操作。
3. 用户在GitHub仓库Settings → Pages选择GitHub Actions作为来源。
4. 用户在Actions页选择 **Publish reviewed public site**，点击 **Run workflow**。触发方式只有workflow_dispatch，没有push触发。
5. build job安装依赖、只构建projects/、检查site全部内容；检查失败则job失败，没有产物上传。deploy job依赖build成功，只有部署job具备pages写入与身份令牌权限。

工作流基于[GitHub官方自定义Pages工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。本轮只准备文件与本地证据，不验证或操作真实GitHub账号、仓库设置及Pages线上部署。
