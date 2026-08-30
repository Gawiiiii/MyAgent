import json
from pathlib import Path

from parser import parse
from tools import list_files, read_file


class MyAgent:
    def __init__(self, model_client, root, max_steps=6):
        self.model_client = model_client
        self.root = Path(root).resolve()
        self.max_steps = max_steps
        self.tools = {"list_files": list_files, "read_file": read_file}

    def prompt(self, user_message, observations=""):
        return "\n".join([
            "You are MyAgent. Work only with the workspace below.",
            f"Workspace: {self.root}",
            "Available tools:",
            '- list_files: list workspace files (args: {})',
            '- read_file: read UTF-8 lines (args: {path, start?, end?})',
            "Respond with exactly one tag: <tool>{\"name\":...,\"args\":{...}}</tool> or <final>answer</final>.",
            f"User request: {user_message}",
            f"Tool results from previous turns:\n{observations}" if observations else "",
        ])

    def ask(self, user_message):
        observations = ""
        for _ in range(self.max_steps):
            raw = self.model_client.complete(self.prompt(user_message, observations), 512)
            result = parse(raw)
            if result["kind"] == "final":
                return result["content"]
            if result["kind"] == "retry":
                observations += f"\nModel format error: {result['error']}. Retry using the required tag."
                continue
            name, args = result["name"], result["args"]
            if name not in self.tools:
                observations += f"\nTool error: unknown tool {name!r}."
                continue
            try:
                output = self.tools[name](self.root, args)
            except (KeyError, ValueError, TypeError, OSError) as exc:
                output = f"error: {exc}"
            observations += f"\n{name} result:\n{output}"
        raise RuntimeError(f"model did not produce a final answer within {self.max_steps} steps")


if __name__ == "__main__":
    from cli import main
    main()
