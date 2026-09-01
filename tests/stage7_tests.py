import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from model_client import FakeModelClient
from my_agent import MyAgent
from session import SessionStore
from workspace import WorkspaceContext


class Stage7Tests(unittest.TestCase):
    def test_preview_contains_unified_diff_without_writing(self):
        with TemporaryDirectory() as directory:
            Path(directory, "a.txt").write_text("old\n", encoding="utf-8")
            agent = MyAgent(FakeModelClient([]), directory, approval="auto")
            preview = agent.preview_tool("write_file", {"path": "a.txt", "content": "new\n"})
            self.assertIn("-old", preview["diff"])
            self.assertIn("+new", preview["diff"])
            self.assertEqual(Path(directory, "a.txt").read_text(encoding="utf-8"), "old\n")

    def test_approval_denial_does_not_write_or_record_change(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(FakeModelClient([]), directory, approval="ask")
            with patch("builtins.input", return_value="n"):
                result = agent.run_tool("write_file", {"path": "new.txt", "content": "blocked"})
            self.assertIn("approval denied", result)
            self.assertFalse(Path(directory, "new.txt").exists())
            self.assertEqual(agent.changes, [])

    def test_write_and_patch_are_recorded_and_can_be_rolled_back(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(FakeModelClient([]), directory, approval="auto")
            agent.run_tool("write_file", {"path": "a.txt", "content": "one"})
            self.assertEqual(Path(directory, "a.txt").read_text(encoding="utf-8"), "one")
            self.assertEqual(agent.rollback(), "removed a.txt")
            self.assertFalse(Path(directory, "a.txt").exists())
            Path(directory, "a.txt").write_text("one", encoding="utf-8")
            agent.run_tool("patch_file", {"path": "a.txt", "old_text": "one", "new_text": "two"})
            change_id = agent.changes[-1]["id"]
            self.assertEqual(agent.rollback(change_id), "rolled back a.txt")
            self.assertEqual(Path(directory, "a.txt").read_text(encoding="utf-8"), "one")

    def test_external_modification_causes_rollback_conflict(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(FakeModelClient([]), directory, approval="auto")
            agent.run_tool("write_file", {"path": "a.txt", "content": "agent"})
            Path(directory, "a.txt").write_text("external", encoding="utf-8")
            result = agent.rollback()
            self.assertIn("rollback conflict", result)
            self.assertEqual(len(agent.changes), 1)

    def test_changes_survive_session_restore(self):
        with TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / ".mini-coding-agent" / "sessions")
            workspace = WorkspaceContext.build(directory)
            agent = MyAgent(FakeModelClient([]), directory, approval="auto", workspace=workspace, session_store=store)
            agent.run_tool("write_file", {"path": "a.txt", "content": "saved"})
            resumed = MyAgent.from_session(FakeModelClient([]), workspace, store, agent.session["id"], approval="auto")
            self.assertEqual(resumed.changes[0]["after"], "saved")

    def test_preview_file_is_read_only(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(FakeModelClient([]), directory)
            result = agent.run_tool("preview_file", {"path": "new.txt", "content": "content"})
            self.assertIn("+content", result)
            self.assertFalse(Path(directory, "new.txt").exists())


if __name__ == "__main__":
    unittest.main()
