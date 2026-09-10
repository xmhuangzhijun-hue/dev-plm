# 纸舟工作助手（明确虚构）

这是 2026-09-05T20:04:49+08:00 创建的 dev-plm 类型样例。它不代表任何真实 Agent，没有运行模型、工具、记忆系统、渠道或生产服务。

`profile.yaml` 组织提示词、工具、记忆、渠道与权限。提示词正文只维护在 `prompts/SEG-PAPER-*.md`；profile 中只有稳定 id、文件和 Git 路径。当前两段与演示仓库 HEAD 逐字节一致。

## 历史从哪里来

本次今天创建了四个真实 Git commit：初始化、修改语气段、修改事实段、撤回语气段修改。所有提交均明确标注 FICTIONAL DEMO CREATED TODAY，作者使用 example.invalid 身份。它们只是客观可查的演示版本，不是补造真实 Agent 的历史。

当前变化单的 repo 为 `../../.work/agent-demo-history`，相对本项目目录定位。bundle 交付后，主仓库根目录可运行：

```powershell
git clone fixtures/agent-demo.bundle .work/agent-demo-history
python build.py
```

恢复前先确认目标 `.work/agent-demo-history` 不存在；已有目录时直接核对其提交，不覆盖或清理。只恢复本地 Git，不安装软件、不联网、不启动服务。保留 bundle 能让另一台机器恢复相同提交。没有恢复时，网页应明确提示无法提取历史。

业务测试、发布和事故均为有明确边界的示例；`tests/` 中的模型行为仍待执行。仓库 URL 和业务本机路径都是虚构地址。
