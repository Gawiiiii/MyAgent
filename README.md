# MyAgent

南京大学软件学院 2026 年预推免考核用本地编程 Agent，支持 OpenAI 兼容 API、内置工具调用、文件测试、会话和只读子agent委派。

## 使用

创建 `.env`：

```env
DEEPSEEK_API_KEY=your-api-key
```

```bash
python3 my_agent.py --cwd ./demo "列出文件并读取 README.md"
python3 my_agent.py --cwd ./demo
```

参数：`--provider`、`--model`、`--approval`、`--resume`、`--max-depth`。

## 工作流程

CLI 准备工作区、会话和模型客户端；`MyAgent.ask` 循环“请求→解析→工具→反馈”直到 `<final>`。支持文件读写/搜索、Shell、预览与回滚；写入先显示 diff 并审批，越界、超时、冲突安全返回，异常响应可恢复。

`delegate`/`delegate_parallel` 启动有限深度只读子 Agent；并行使用线程池。

## 模块功能

- `my_agent.py`：主循环、审批、工具编排和委派。
- `model_client.py`：OpenAI 兼容、Ollama、Fake 客户端。
- `tools.py`：文件、搜索、补丁、Shell、预览和校验。
- `parser.py`：解析单个 JSON `<tool>` 调用和 `<final>` 最终回答。
- `context.py`：Prompt、记忆、历史压缩。
- `workspace.py`：工作目录、Git 和文档上下文。
- `session.py`：JSON 会话保存、恢复。
- `changes.py`：diff、冲突检查和回滚记录。
- `audit.py`：JSONL 审计、裁剪和敏感信息脱敏。
- `cli.py`：命令行与 REPL。
- `tests/`：单元测试和可选真实 API 集成测试。

## 数据与测试

数据位于 `.mini-coding-agent/`。测试：`python3 -m unittest discover -v` 或 `pytest -q`；真实 API 需设置开关。Python `>=3.10`。
