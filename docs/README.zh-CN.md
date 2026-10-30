# MiniClaudeCode

基于 Python、AsyncIO、Rich 和 SQLite 的本地编程 Agent，配套独立的 Audit 评测工具。支持读取仓库、规划、修改文件、运行测试和恢复会话。

## 实现范围

- OpenAI / Anthropic 兼容接口、SSE 流式输出、指数退避与 jitter；部分输出或工具调度后不重放请求。
- 13 个工具，初始提供 5 个 Schema，通过 `discover_tools` 延迟启用其余工具。
- 只读工具并发执行；Anthropic 完成工具块后可提前调度读取，写操作等待完整回复。
- 四阶段压缩：预算截断、过期读取删除、轻量压缩、模型摘要。
- SQLite 跨会话记忆、side-query 扩展、模型语义排序、异步预取、时效提醒及明确标注的词法回退。
- 五种权限模式、声明式 allow/deny、16 项危险命令检查、精确参数白名单。
- 编辑前读取、文件摘要校验、唯一匹配替换、Python 语法检查。
- 会话保存恢复、斜杠命令、分层 `CLAUDE.md`、递归 `@include`、规则注入。
- Audit 包括 26 个重建任务契约、独立验证器、轨迹、失败归类、指标聚合和消融实验。

## 安装与运行

需要 Python 3.12+。Windows PowerShell：

```powershell
git clone https://github.com/tonglynn/MiniClaudeCode.git
cd MiniClaudeCode
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:LLM_PROTOCOL = 'openai'
$env:LLM_BASE_URL = 'https://api.deepseek.com'
$env:LLM_MODEL = '<账户支持的模型 ID>'
$env:LLM_API_KEY = '<你的 API Key>'
miniclaudecode --workspace 'C:\path\to\repo'
```

也可复制根目录 `.provider.example.json` 为 `.provider_private.json` 并在本地填写。环境变量优先；密钥不随仓库提供。Base URL 不包含 `/chat/completions` 或 `/messages` 后缀。

默认 `ask` 模式，写入和执行需确认，显式 allow 规则除外。`auto_edit` 自动允许写入，`auto` 自动允许通过内建检查的操作；`read_only` 和 `plan` 禁止写入与执行。命令工具只支持 Git status/diff/log 和 Python pytest/unittest，并不提供任意 Shell。

交互命令：`/help`、`/new`、`/sessions`、`/resume ID`、`/save`、`/mode MODE`、`/memory QUERY`、`/plan`、`/tools`、`/exit`。

## 验证

```powershell
python -m pytest -q
miniclaude-audit --offline-check
```

离线检查确认 26 个契约能够拒绝错误实现、接受参考实现，不调用模型，不能作为模型完成率。真实单任务评测：

```powershell
miniclaude-audit --task t01_clamp
```

评测会消耗 API 额度，结果在 `runs/`。完整的五策略、三次重复实验共 390 次任务，应先验证单任务。

## 结果边界

这是按 CV 功能描述整理的可运行重建版本。缺少原始源码、原任务集与历史日志，因此不声称复现 CV 中的 72%→88%、7K Token、15%、31%、43%、91%、100% 或 12% 等历史实验数字。本次发布实际检查见 [验证记录](../VERIFICATION.md)。

上下文预算使用字符数而非精确 Token；记忆通过候选检索与模型排序实现，不是向量数据库。权限和路径检查属于应用层保护，不是操作系统沙箱；运行测试会执行项目代码，不可信仓库应放入独立隔离环境。

[English README](../README.md) · [实现设计](design.md)
