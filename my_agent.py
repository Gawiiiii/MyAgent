from pathlib import Path

from parser import parse
from tools import build_tools, validate_tool


class MyAgent:
    def __init__(self, model_client, root, max_steps=6, approval="ask", max_new_tokens=512):
        """初始化 Agent；参数为模型客户端、根目录、步数、审批模式和 token 上限，返回 None。"""
        self.model_client = model_client
        self.root = Path(root).resolve()
        self.max_steps = max_steps
        self.approval = approval
        self.max_new_tokens = max_new_tokens
        self.tools = build_tools(self)

    def prompt(self, user_message, observations=""):
        """构造模型提示；参数为用户 str 请求和工具结果 str，返回完整 Prompt str。"""
        tool_text = "\n".join(f"- {name}: {item['description']} (args: {item['schema']})" for name, item in self.tools.items())
        return "\n".join([
            "You are a coding agent. Work only with the workspace below.",
            f"Workspace: {self.root}",
            "Available tools:",
            tool_text,
            'Respond with <tool>{"name":...,"args":{...}}</tool>, XML write/patch tool tags, or <final>answer</final>.',
            f"User request: {user_message}",
            f"Tool results from previous turns:\n{observations}" if observations else "",
        ])

    def ask(self, user_message):
        """循环请求模型并执行工具；参数为用户 str 请求，返回最终答案 str。"""
        observations = ""
        for _ in range(self.max_steps):
            raw = self.model_client.complete(self.prompt(user_message, observations), self.max_new_tokens)
            result = parse(raw)
            if result["kind"] == "final":
                return result["content"]
            if result["kind"] == "retry":
                observations += f"\nModel format error: {result['error']}. Retry using the required tag."
                continue
            name, args = result["name"], result["args"]
            output = self.run_tool(name, args)
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


if __name__ == "__main__":
    from cli import main
    main()
