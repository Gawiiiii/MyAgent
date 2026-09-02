import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from audit import AuditLog
from changes import (
    ChangeRecord,
    apply_change,
    preview_change,
    rollback_change,
    timestamp,
)
from context import build_prompt
from parser import parse
from session import SessionStore
from tools import build_tools, validate_tool
from workspace import WorkspaceContext


class MyAgent:
    def __init__(self, model_client, root, max_steps=6, approval="ask", max_new_tokens=4096, workspace=None, session_store=None, session=None, depth=0, max_depth=1, read_only=False, max_parallel_delegates=3, persist_session=True, audit_log=None):
        """初始化 Agent；参数为模型客户端、根目录、运行配置及可选上下文会话，返回 None。"""
        self.model_client = model_client
        self.workspace = workspace or WorkspaceContext.build(root)
        self.root = Path(self.workspace.repo_root).resolve()
        self.max_steps = max_steps
        self.approval = approval
        self.max_new_tokens = max_new_tokens
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
        observations, attempts, tool_steps, empty_responses = "", 0, 0, 0
        tool_calls = set()
        max_attempts = max(self.max_steps * 3, self.max_steps + 4)
        while attempts < max_attempts:
            attempts += 1
            prompt = self.prompt(user_message, observations)
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
                self.record({"role": "assistant", "content": result["content"]})
                self.audit_log.append("final_answer", content=result["content"])
                return result["content"]
            if result["kind"] == "retry":
                self.record({"role": "assistant", "content": f"format error: {result['error']}"})
                if result["error"] == "empty response":
                    empty_responses += 1
                    if empty_responses >= 3:
                        stop = "Stopped after 3 consecutive empty model responses. Check the model output limit and provider response metadata."
                        self.record({"role": "assistant", "content": stop})
                        self.audit_log.append("final_answer", content=stop)
                        return stop
                else:
                    empty_responses = 0
                observations += f"\nModel format error: {result['error']}. Retry using the required tag."
                continue
            empty_responses = 0
            name, args = result["name"], result["args"]
            if tool_steps >= self.max_steps:
                break
            tool_steps += 1
            if self.repeated_tool_call(name, args, tool_calls):
                output = f"error: repeated tool call for {name} with identical arguments"
                self.note_tool(name, args, output)
                observations += f"\n{name} result:\n{output}"
                if tool_steps >= self.max_steps:
                    break
                continue
            tool_calls.add(self.tool_call_key(name, args))
            self.audit_log.append("tool_start", name=name, args=args)
            output = self.run_tool(name, args)
            self.audit_log.append("tool_error" if output.startswith("error:") else "tool_result", name=name, result=output)
            self.note_tool(name, args, output)
            observations += f"\n{name} result:\n{output}"
        stop = f"Stopped after {attempts} attempts and {tool_steps} tool steps without a final answer."
        self.record({"role": "assistant", "content": stop})
        self.audit_log.append("final_answer", content=stop)
        return stop

    @staticmethod
    def tool_call_key(name, args):
        """生成工具调用比较键；参数为名称和参数字典，返回规范字符串。"""
        return f"{name}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"

    def repeated_tool_call(self, name, args, tool_calls=None):
        """判断当前 ask 内工具调用是否重复；参数为名称、参数和调用集合，返回 bool。"""
        return self.tool_call_key(name, args) in (tool_calls or set())

    def approve(self, name, args, preview=""):
        """决定风险工具是否执行；参数为工具名 str 和参数 dict，返回允许执行的 bool。"""
        if not self.tools[name]["risky"]:
            return True
        if self.approval == "auto":
            return True
        if self.approval == "never":
            return False
        if preview:
            print(preview["diff"])
        answer = input(f"Allow {name} with {args}? [y/N] ").strip().lower()
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
            audit_log=self.audit_log,
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
