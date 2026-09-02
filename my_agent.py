from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from audit import AuditLog
from changes import (
    ChangeRecord,
    apply_change,
    format_diff,
    preview_change,
    rollback_change,
    timestamp,
)
from context import build_prompt
from parser import parse
from session import SessionStore
from tools import build_tools, validate_tool
from workspace import WorkspaceContext

FORMAT_ERROR_LIMIT = 3
TOOL_FORMAT_EXAMPLE = '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>'


class MyAgent:
    def __init__(self, model_client, root, max_steps=6, approval="ask", max_new_tokens=4096, workspace=None, session_store=None, session=None, depth=0, max_depth=1, read_only=False, max_parallel_delegates=3, persist_session=True, audit_log=None, unlimited_tool_calls=True, status=None):
        """初始化 Agent；参数为模型客户端、根目录、运行配置及可选上下文会话，返回 None。"""
        self.model_client = model_client
        self.workspace = workspace or WorkspaceContext.build(root)
        self.root = Path(self.workspace.cwd).resolve()
        self.max_steps = max_steps
        self.approval = approval
        self.max_new_tokens = max_new_tokens
        self.unlimited_tool_calls = unlimited_tool_calls
        self.status = status
        self.depth = depth
        self.max_depth = max_depth
        self.read_only = read_only
        if not 1 <= max_parallel_delegates <= 8:
            raise ValueError("max_parallel_delegates must be between 1 and 8")
        self.max_parallel_delegates = max_parallel_delegates
        self.persist_session = persist_session
        self.tools = build_tools(self)
        self.session_store = session_store or SessionStore(self.root / ".mini-coding-agent" / "sessions")
        self.session = session or {"id": datetime.now().strftime("%Y%m%d-%H%M%S-%f"), "created_at": datetime.now(timezone.utc).isoformat(), "workspace_root": str(self.root), "history": [], "memory": {"task": "", "files": [], "notes": []}, "changes": []}
        self.session.setdefault("changes", [])
        self.changes = self.session["changes"]
        self.audit_log = audit_log or AuditLog(self.root / ".mini-coding-agent" / "audit" / f"{self.session['id']}.jsonl")

    def _save_session(self):
        """按持久化开关保存当前会话；参数为 self，返回 None。"""
        if self.persist_session:
            self.session_store.save(self.session)

    @classmethod
    def from_session(cls, model_client, workspace, session_store, session_id, **kwargs):
        """从磁盘恢复 Agent；参数为客户端、工作区、存储器、会话 ID 和运行配置，返回 MyAgent。"""
        session = session_store.load(session_id)
        return cls(model_client, workspace.repo_root, workspace=workspace, session_store=session_store, session=session, **kwargs)

    def prompt(self, user_message, observations=""):
        """构造模型提示；参数为用户 str 请求和工具结果 str，返回完整 Prompt str。"""
        prompt = build_prompt(self, user_message)
        return prompt + (f"\n\nTool results from current turn:\n{observations}" if observations else "")

    def ask(self, user_message):
        """循环请求模型并执行工具；参数为用户 str 请求，返回最终答案 str。"""
        self.record({"role": "user", "content": user_message})
        self.session["memory"]["task"] = user_message
        self._save_session()
        observations, attempts, tool_steps, empty_responses, format_errors = "", 0, 0, 0, 0
        retry_reads, last_retry_path = 0, None
        max_attempts = max(self.max_steps * 3, self.max_steps + 4)
        while True:
            attempts += 1
            prompt = self.prompt(user_message, observations)
            self._status("Requesting LLM...")
            self.audit_log.append("model_request", attempt=attempts, max_new_tokens=self.max_new_tokens)
            try:
                raw = self.model_client.complete(prompt, self.max_new_tokens)
            except RuntimeError as exc:
                self.audit_log.append("model_error", attempt=attempts, error=str(exc))
                raise
            metadata = getattr(self.model_client, "last_response_metadata", {})
            self.audit_log.append("model_response", attempt=attempts, output=raw, **metadata)
            result = parse(raw)
            self.audit_log.append("parse_result", kind=result.get("kind"), error=result.get("error", ""))
            if result["kind"] == "final":
                self._status("")
                self.record({"role": "assistant", "content": result["content"]})
                self.audit_log.append("final_answer", content=result["content"])
                return result["content"]
            if result["kind"] == "retry":
                format_errors += 1
                # Preserve the exact model text in the session as well as the
                # audit's model_response event, so format failures can be
                # diagnosed from persisted data rather than inferred.
                self.record({
                    "role": "assistant",
                    "content": (
                        f"format error: {result['error']}\n"
                        "raw model response:\n"
                        f"{raw}"
                    ),
                })
                self.audit_log.append(
                    "format_error",
                    attempt=attempts,
                    error=result["error"],
                    raw_response=raw,
                )
                if result["error"] == "empty response":
                    empty_responses += 1
                    if empty_responses >= 3:
                        stop = "Stopped after 3 consecutive empty model responses. Check the model output limit and provider response metadata."
                        self.record({"role": "assistant", "content": stop})
                        self.audit_log.append("final_answer", content=stop)
                        self._status("")
                        return stop
                else:
                    empty_responses = 0
                if format_errors >= FORMAT_ERROR_LIMIT:
                    stop = (
                        f"Agent stopped after {FORMAT_ERROR_LIMIT} consecutive invalid model responses. "
                        "The model did not follow the required tool format. "
                        f"Expected exactly one JSON tool call, for example: {TOOL_FORMAT_EXAMPLE}"
                    )
                    self.record({"role": "assistant", "content": stop})
                    self.audit_log.append("final_answer", content=stop)
                    self._status("")
                    return stop
                observations += (
                    f"\nModel format error: {result['error']}. Output exactly one JSON-tagged call, "
                    f"with no markdown or XML. Example: {TOOL_FORMAT_EXAMPLE}"
                )
                continue
            empty_responses = 0
            format_errors = 0
            name, args = result["name"], result["args"]
            if not self.unlimited_tool_calls and tool_steps >= self.max_steps:
                break
            tool_steps += 1
            if name == "read_file" and args.get("retry") is True:
                retry_path = args.get("path")
                retry_reads = retry_reads + 1 if retry_path == last_retry_path else 1
                last_retry_path = retry_path
            else:
                retry_reads, last_retry_path = 0, None
            if retry_reads > 3:
                output = f"error: repeated retry read limit reached for {args.get('path')}"
                self.note_tool(name, args, output)
                observations += f"\n{name} result:\n{output}"
                if not self.unlimited_tool_calls and tool_steps >= self.max_steps:
                    break
                continue
            self._status(self._tool_status(name, args))
            self.audit_log.append("tool_start", name=name, args=args)
            output = self.run_tool(name, args)
            self.audit_log.append("tool_error" if output.startswith("error:") else "tool_result", name=name, result=output)
            self.note_tool(name, args, output)
            observations += f"\n{name} result:\n{output}"
        stop = f"Stopped after {attempts} attempts and {tool_steps} tool steps without a final answer."
        self.record({"role": "assistant", "content": stop})
        self.audit_log.append("final_answer", content=stop)
        self._status("")
        return stop

    def _status(self, message):
        """更新单行执行状态；参数为状态文本，返回 None。"""
        if self.status:
            self.status(message)

    def _tool_status(self, name, args):
        """生成包含操作目标的工具状态文本；参数为工具名和参数字典，返回 str。"""
        args = args if isinstance(args, dict) else {}
        if name == "list_files":
            detail = f"in {self.root}"
        elif name in {"read_file", "write_file", "patch_file", "preview_file"}:
            detail = str(args.get("path", "(unknown path)"))
        elif name == "search":
            detail = f"pattern={args.get('pattern', '(unknown pattern)')}"
        elif name == "run_shell":
            detail = f"command={args.get('command', '(unknown command)')}"
        elif name == "delegate":
            detail = f"task={args.get('task', '(unknown task)')}"
        elif name == "delegate_parallel":
            detail = f"{len(args.get('tasks', []))} tasks"
        else:
            detail = ""
        return f"Tool calling {name} {detail}..." if detail else f"Tool calling {name}..."

    def approve(self, name, args, preview=""):
        """决定风险工具是否执行；参数为工具名 str 和参数 dict，返回允许执行的 bool。"""
        if not self.tools[name]["risky"]:
            return True
        if self.approval == "auto":
            return True
        if self.approval == "never":
            return False
        if preview:
            self._status("")
            print(format_diff(preview["diff"]))
        else:
            self._status("")
        print(f"Allow {name} with {args}?")
        answer = input("【y/n】 ").strip().lower()
        return answer in {"y", "yes"}

    def run_tool(self, name, args):
        """校验、审批并执行工具；参数为工具名 str 和参数 dict，返回结果或错误 str。"""
        if name not in self.tools:
            return f"error: unknown tool {name!r}"
        try:
            if self.read_only and name not in {"list_files", "read_file", "search"}:
                return f"error: read-only agent cannot use {name}"
            validate_tool(self.root, name, args)
            if name in {"write_file", "patch_file"}:
                change = self.preview_tool(name, args)
                if not self.approve(name, args, change):
                    return f"error: approval denied for {name}"
                applied = apply_change(self.root, args["path"], name, change["before"], change["after"])
                record = ChangeRecord(args["path"], change["before"], change["after"], name, timestamp())
                record_id = max((item.get("id", 0) for item in self.changes), default=0) + 1
                self.changes.append({"id": record_id, "path": record.path, "before": record.before, "after": record.after, "operation": record.operation, "timestamp": record.timestamp, "diff": change["diff"]})
                self._save_session()
                return f"{applied}\n{change['diff']}"
            if not self.approve(name, args):
                return f"error: approval denied for {name}"
            return self.tools[name]["run"](self.root, args)
        except (KeyError, ValueError, TypeError, OSError) as exc:
            return f"error: {exc}"

    def preview_tool(self, name, args):
        """计算写入或补丁的变更预览；参数为工具名和参数字典，返回 before/after/diff 字典。"""
        target = self.root / args["path"]
        before = target.read_text(encoding="utf-8") if target.exists() else None
        if name == "write_file":
            after = args["content"]
        elif name == "patch_file":
            if before is None:
                raise ValueError(f"not a file: {args['path']}")
            occurrences = before.count(args["old_text"])
            if occurrences != 1:
                raise ValueError(f"old_text must occur exactly once (found {occurrences})")
            after = before.replace(args["old_text"], args["new_text"])
        else:
            raise ValueError(f"preview is not supported for {name}")
        return {"before": before, "after": after, "diff": preview_change(self.root, args["path"], name, before, after)}

    def rollback(self, change_id=None):
        """回滚最近或指定变更；参数为可选整数变更 ID，返回操作摘要或错误文本。"""
        if not self.changes:
            return "error: no changes to roll back"
        try:
            selected = self.changes[-1] if change_id is None else next(item for item in self.changes if item.get("id") == int(change_id))
        except (StopIteration, TypeError, ValueError):
            return f"error: change not found: {change_id}"
        record = ChangeRecord(selected["path"], selected["before"], selected["after"], selected["operation"], selected["timestamp"])
        try:
            result = rollback_change(self.root, record)
        except (OSError, ValueError) as exc:
            return f"error: {exc}"
        self.changes.remove(selected)
        self._save_session()
        return result

    def tool_delegate(self, args):
        """运行受限只读子 Agent；参数为含 task 的 dict，返回 delegate_result 文本。"""
        if not isinstance(args, dict) or not isinstance(args.get("task"), str) or not args["task"].strip():
            raise ValueError("task must not be empty")
        if self.depth >= self.max_depth:
            raise ValueError("maximum delegation depth reached")
        self.audit_log.append("delegation_start", task=args["task"])
        child = self._build_read_only_child()
        answer = child.ask(args["task"])
        self.audit_log.append("delegation_end", result=answer)
        return f"delegate_result: {answer}"

    def _build_read_only_child(self):
        """创建共享客户端和工作区的只读子 Agent；参数为 self，返回 MyAgent。"""
        return MyAgent(
            self.model_client, self.root, max_steps=self.max_steps,
            approval="never", max_new_tokens=self.max_new_tokens,
            workspace=self.workspace, session_store=self.session_store,
            depth=self.depth + 1, max_depth=self.max_depth, read_only=True,
            max_parallel_delegates=self.max_parallel_delegates, persist_session=False,
            audit_log=self.audit_log, unlimited_tool_calls=self.unlimited_tool_calls,
            status=self.status,
        )

    def tool_delegate_parallel(self, args):
        """并行执行多个只读委派任务；参数为含 tasks 列表的 dict，返回有序结果文本。"""
        tasks = args.get("tasks") if isinstance(args, dict) else None
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("tasks must be a non-empty list")
        if len(tasks) > self.max_parallel_delegates:
            raise ValueError(f"tasks must contain at most {self.max_parallel_delegates} items")
        if self.depth >= self.max_depth:
            raise ValueError("maximum delegation depth reached")
        self.audit_log.append("delegation_start", tasks=tasks)

        def execute(task):
            if not isinstance(task, str) or not task.strip():
                return "error: task must not be empty"
            try:
                return self._build_read_only_child().ask(task)
            except RuntimeError as exc:
                return f"error: {exc}"

        with ThreadPoolExecutor(max_workers=min(len(tasks), self.max_parallel_delegates)) as executor:
            results = list(executor.map(execute, tasks))
        output = "\n".join(f"delegate_result[{index}]: {result}" for index, result in enumerate(results, 1))
        self.audit_log.append("delegation_end", result=output)
        return output

    def record(self, item):
        """追加并立即保存历史记录；参数为 dict 记录项，返回 None。"""
        self.session["history"].append(item)
        self._save_session()

    def note_tool(self, name, args, result):
        """记录工具访问和结果摘要；参数为名称、参数字典和结果字符串，返回 None。"""
        if args.get("path") and args["path"] not in self.session["memory"]["files"]:
            self.session["memory"]["files"].append(args["path"])
        self.record({"role": "tool", "name": name, "args": args, "content": result})

    def reset(self):
        """清空当前会话历史和记忆；参数为 self，返回 None。"""
        self.session["history"] = []
        self.session["memory"] = {"task": "", "files": [], "notes": []}
        self._save_session()


if __name__ == "__main__":
    from cli import main
    main()
