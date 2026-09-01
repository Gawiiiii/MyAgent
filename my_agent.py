from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from context import build_prompt
from parser import parse
from session import SessionStore
from tools import build_tools, validate_tool
from workspace import WorkspaceContext


class MyAgent:
    def __init__(self, model_client, root, max_steps=6, approval="ask", max_new_tokens=512, workspace=None, session_store=None, session=None, depth=0, max_depth=1, read_only=False, max_parallel_delegates=3):
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
        self.tools = build_tools(self)
        self.session_store = session_store or SessionStore(self.root / ".mini-coding-agent" / "sessions")
        self.session = session or {"id": datetime.now().strftime("%Y%m%d-%H%M%S-%f"), "created_at": datetime.now(timezone.utc).isoformat(), "workspace_root": str(self.root), "history": [], "memory": {"task": "", "files": [], "notes": []}}
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
        self.session_store.save(self.session)
        observations, attempts, tool_steps = "", 0, 0
        max_attempts = max(self.max_steps * 3, self.max_steps + 4)
        while attempts < max_attempts and tool_steps < self.max_steps:
            attempts += 1
            raw = self.model_client.complete(self.prompt(user_message, observations), self.max_new_tokens)
            result = parse(raw)
            if result["kind"] == "final":
                self.record({"role": "assistant", "content": result["content"]})
                return result["content"]
            if result["kind"] == "retry":
                self.record({"role": "assistant", "content": f"format error: {result['error']}"})
                observations += f"\nModel format error: {result['error']}. Retry using the required tag."
                continue
            name, args = result["name"], result["args"]
            tool_steps += 1
            if self.repeated_tool_call(name, args):
                output = f"error: repeated tool call for {name} with identical arguments"
                self.note_tool(name, args, output)
                observations += f"\n{name} result:\n{output}"
                continue
            output = self.run_tool(name, args)
            self.note_tool(name, args, output)
            observations += f"\n{name} result:\n{output}"
        stop = f"Stopped after {attempts} attempts and {tool_steps} tool steps without a final answer."
        self.record({"role": "assistant", "content": stop})
        return stop

    def repeated_tool_call(self, name, args):
        """判断工具调用是否重复；参数为工具名 str 和参数 dict，返回 bool。"""
        return any(item.get("role") == "tool" and item.get("name") == name and item.get("args") == args for item in self.session["history"])

    def approve(self, name, args):
        """决定风险工具是否执行；参数为工具名 str 和参数 dict，返回允许执行的 bool。"""
        if not self.tools[name]["risky"]:
            return True
        if self.approval == "auto":
            return True
        if self.approval == "never":
            return False
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
            if not self.approve(name, args):
                return f"error: approval denied for {name}"
            return self.tools[name]["run"](self.root, args)
        except (KeyError, ValueError, TypeError, OSError) as exc:
            return f"error: {exc}"

    def tool_delegate(self, args):
        """运行受限只读子 Agent；参数为含 task 的 dict，返回 delegate_result 文本。"""
        if not isinstance(args, dict) or not isinstance(args.get("task"), str) or not args["task"].strip():
            raise ValueError("task must not be empty")
        if self.depth >= self.max_depth:
            raise ValueError("maximum delegation depth reached")
        child = self._build_read_only_child()
        answer = child.ask(args["task"])
        return f"delegate_result: {answer}"

    def _build_read_only_child(self):
        """创建共享客户端和工作区的只读子 Agent；参数为 self，返回 MyAgent。"""
        return MyAgent(
            self.model_client, self.root, max_steps=self.max_steps,
            approval="never", max_new_tokens=self.max_new_tokens,
            workspace=self.workspace, session_store=self.session_store,
            depth=self.depth + 1, max_depth=self.max_depth, read_only=True,
            max_parallel_delegates=self.max_parallel_delegates,
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

        def execute(task):
            if not isinstance(task, str) or not task.strip():
                return "error: task must not be empty"
            try:
                return self._build_read_only_child().ask(task)
            except RuntimeError as exc:
                return f"error: {exc}"

        with ThreadPoolExecutor(max_workers=min(len(tasks), self.max_parallel_delegates)) as executor:
            results = list(executor.map(execute, tasks))
        return "\n".join(f"delegate_result[{index}]: {result}" for index, result in enumerate(results, 1))

    def record(self, item):
        """追加并立即保存历史记录；参数为 dict 记录项，返回 None。"""
        self.session["history"].append(item)
        self.session_store.save(self.session)

    def note_tool(self, name, args, result):
        """记录工具访问和结果摘要；参数为名称、参数字典和结果字符串，返回 None。"""
        if args.get("path") and args["path"] not in self.session["memory"]["files"]:
            self.session["memory"]["files"].append(args["path"])
        self.record({"role": "tool", "name": name, "args": args, "content": result})

    def reset(self):
        """清空当前会话历史和记忆；参数为 self，返回 None。"""
        self.session["history"] = []
        self.session["memory"] = {"task": "", "files": [], "notes": []}
        self.session_store.save(self.session)


if __name__ == "__main__":
    from cli import main
    main()
