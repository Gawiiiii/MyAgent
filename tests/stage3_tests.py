import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from context import build_prompt, history_text, memory_text
from my_agent import MyAgent
from session import SessionStore
from workspace import WorkspaceContext


class FinalClient:
    """返回固定最终答案的测试客户端。"""

    def complete(self, _prompt, _tokens):
        """返回最终标签；参数为 Prompt 和 token 上限，返回 str。"""
        return "<final>done</final>"


class Stage3Tests(unittest.TestCase):
    def test_workspace_context_and_prompt_include_project_facts(self):
        with TemporaryDirectory() as directory:
            Path(directory, "README.md").write_text("project docs", encoding="utf-8")
            workspace = WorkspaceContext.build(directory)
            agent = MyAgent(FinalClient(), directory, workspace=workspace)
            prompt = build_prompt(agent, "inspect")
            self.assertIn(str(Path(directory).resolve()), prompt)
            self.assertIn("project docs", prompt)

    def test_session_records_and_resumes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionStore(root / ".mini-coding-agent" / "sessions")
            workspace = WorkspaceContext.build(root)
            agent = MyAgent(FinalClient(), root, workspace=workspace, session_store=store)
            self.assertEqual(agent.ask("remember this"), "done")
            loaded = store.load(agent.session["id"])
            self.assertEqual([item["role"] for item in loaded["history"]], ["user", "assistant"])
            resumed = MyAgent.from_session(FinalClient(), workspace, store, agent.session["id"])
            self.assertEqual(resumed.session["history"][0]["content"], "remember this")

    def test_reset_clears_history_and_memory(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(FinalClient(), directory)
            agent.ask("temporary")
            agent.session["memory"]["files"].append("x.py")
            agent.reset()
            self.assertEqual(agent.session["history"], [])
            self.assertEqual(agent.session["memory"], {"task": "", "files": [], "notes": []})

    def test_context_helpers_format_saved_state(self):
        session = {"memory": {"task": "task", "files": ["a.py"], "notes": ["note"]}, "history": [{"role": "user", "content": "hi"}]}
        self.assertIn("task", memory_text(session))
        self.assertIn("a.py", memory_text(session))
        self.assertIn("[user] hi", history_text(session["history"]))


if __name__ == "__main__":
    unittest.main()
