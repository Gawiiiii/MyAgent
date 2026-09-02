# MyAgent

用于南京大学软件学院2026年预推免项目考核。
一个简单的本地编程 Agent，支持 OpenAI 兼容 API、Ollama、工作区文件操作、Shell 测试、会话恢复和受限只读子 Agent 委派。

## 快速开始

在项目目录创建 `.env`，写入 Deepseek API 密钥，因为本项目构建时使用 deepseek API，所以默认使用该API，如需更换站点，需要运行命令时手动指定参数。

```env
DEEPSEEK_API_KEY=your-api-key
```

（也可以直接设置环境变量）

一次性执行任务：

```bash
python3 my_agent.py --cwd ./demo "列出文件并读取 README.md"
```
上述指令会在./demo目录下执行"列出文件并读取 README.md"请求。

交互式运行：

```bash
python3 my_agent.py --cwd ./demo
```
上述指令会在./demo目录下开启交互式运行。

常用选项：`--provider openai-compatible|ollama`、`--model`、`--approval ask|auto|never`、`--max-steps`、`--resume latest`、`--max-depth`、`--max-parallel-delegates`。

`--max-new-tokens` 可设置单次模型响应上限，默认值为 `4096`。

## 工作流程

```text
CLI
 ↓
WorkspaceContext + SessionStore + ModelClient
 ↓
MyAgent.ask
 ↓
构造 Prompt → 调用 LLM → 解析 <tool>/<final>
                         ↓
          校验并执行文件、搜索、Shell 或委派工具
                         ↓
                 将结果加入下一轮 Prompt
```

`delegate_parallel` 使用线程池并行执行多个只读分析任务；子 Agent 共享模型客户端和工作区，但只能读取和搜索，不能写文件、运行 Shell 或继续委派。

写入或补丁操作会先生成统一 diff 供审批，并保存可回滚的变更记录；模型格式异常会自动重试，连续三次空响应时安全停止。

## 项目结构

| 文件 | 职责 |
| --- | --- |
| `my_agent.py` | Agent 循环、审批、会话记录和委派 |
| `audit.py` | JSONL 审计日志、内容裁剪和敏感字段脱敏 |
| `changes.py` | 文件变更预览、冲突检查和回滚 |
| `model_client.py` | OpenAI 兼容客户端、Ollama 客户端和 `FakeModelClient` |
| `tools.py` | 文件读写、搜索、补丁、Shell、委派工具及校验 |
| `parser.py` | 解析 `<tool>`、XML 写入/补丁和 `<final>` |
| `context.py` | Prompt、工作记忆和历史压缩 |
| `workspace.py` | Git 状态和项目文档上下文 |
| `session.py` | JSON 会话保存、加载和 latest 查找 |
| `cli.py` | 命令行参数和交互式 REPL |
| `tests/` | 包含阶段测试和调用 API 的集成测试 |

## 会话数据

会话保存在 `.mini-coding-agent/sessions/<session_id>.json`，包含用户/工具/助手历史以及当前记忆：

```json
{
  "id": "20260901-120000-123456",
  "workspace_root": "/tmp/project",
  "history": [
    {"role": "user", "content": "读取 README.md"},
    {"role": "tool", "name": "read_file", "args": {"path": "README.md"}, "content": "1: docs"},
    {"role": "assistant", "content": "读取完成"}
  ],
  "memory": {"task": "读取 README.md", "files": ["README.md"], "notes": []}
}
```

使用 `--resume latest` 恢复最近会话；REPL 支持 `/help`、`/memory`、`/session`、`/reset`、`/exit` 和 `/quit`。

REPL 还支持 `/diff` 查看变更、`/rollback [id]` 回滚变更、`/audit [N]` 查看审计事件和 `/audit-clear` 清空审计日志。

审计日志保存在 `.mini-coding-agent/audit/<session_id>.jsonl`，记录模型调用、解析、工具执行和委派事件，并包含可用的响应结束原因与 token 用量。

## 测试与开发

```bash
python3 -m unittest discover -v
python3 -m pytest -q
ruff check .
```

真实 API 测试默认跳过。配置 `.env` 后，显式设置 `MYAGENT_RUN_FULL_TESTS=1` 才会运行：

```bash
MYAGENT_RUN_FULL_TESTS=1 python3 -m unittest tests.full_test_3 -v
```

项目要求 Python `>=3.10`，开发依赖可通过 `pip install -e '.[dev]'` 安装；命令入口为 `my-agent` 和 `mini-agent`。
