from pathlib import Path
from datetime import datetime, timezone

from context import build_prompt
from parser import parse
from tools import build_tools, validate_tool
from workspace import WorkspaceContext
from session import SessionStore


class MyAgent:
    def __init__(self, model_client, root, max_steps=6, approval="ask", max_new_tokens=512, workspace=None, session_store=None, session=None):
        """初始化 Agent；参数为模型客户端、根目录、运行配置及可选上下文会话，返回 None。"""
        self.model_client = model_client
        self.workspace = workspace or WorkspaceContext.build(root)
        self.root = Path(self.workspace.repo_root).resolve()
        self.max_steps = max_steps
        self.approval = approval
        self.max_new_tokens = max_new_tokens
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
        observations = ""
        for _ in range(self.max_steps):
            raw = self.model_client.complete(self.prompt(user_message, observations), self.max_new_tokens)
            result = parse(raw)
            if result["kind"] == "final":
                self.record({"role": "assistant", "content": result["content"]})
                return result["content"]
            if result["kind"] == "retry":
                observations += f"\nModel format error: {result['error']}. Retry using the required tag."
                continue
            name, args = result["name"], result["args"]
            output = self.run_tool(name, args)
            self.note_tool(name, args, output)
            observations += f"\n{name} result:\n{output}"
        raise RuntimeError(f"model did not produce a final answer within {self.max_steps} steps")

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
            validate_tool(self.root, name, args)
            if not self.approve(name, args):
                return f"error: approval denied for {name}"
            return self.tools[name]["run"](self.root, args)
        except (KeyError, ValueError, TypeError, OSError) as exc:
            return f"error: {exc}"

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
