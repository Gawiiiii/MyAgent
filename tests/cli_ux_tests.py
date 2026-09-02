import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import cli
from changes import DIFF_SEPARATOR, format_diff
from model_client import FakeModelClient
from my_agent import MyAgent
from session import SessionStore


class CliUxTests(unittest.TestCase):
    """覆盖终端展示、审批和交互式会话恢复。"""

    def test_format_diff_adds_visible_boundaries(self):
        rendered = format_diff("--- a/a.txt\n+++ b/a.txt\n")
        self.assertEqual(rendered.count(DIFF_SEPARATOR), 3)
        self.assertIn("DIFF", rendered)

    def test_approval_prints_detail_before_separate_answer_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            agent = MyAgent(FakeModelClient([]), root, approval="ask")
            output = io.StringIO()
            with redirect_stdout(output), patch("builtins.input", return_value="y") as ask:
                allowed = agent.approve("write_file", {"path": "a.txt"}, {"diff": "sample diff"})
            self.assertTrue(allowed)
            self.assertIn("Allow write_file with {'path': 'a.txt'}?", output.getvalue())
            self.assertIn(DIFF_SEPARATOR, output.getvalue())
            ask.assert_called_once_with("【y/n】 ")

    def test_help_describes_every_command(self):
        for command in ("/help", "/memory", "/session", "/diff", "/rollback", "/audit", "/audit-clear", "/reset", "/exit", "/quit"):
            self.assertIn(command, cli.HELP_TEXT)
        self.assertIn("Show all active changes", cli.HELP_TEXT)
        self.assertIn("Roll back the latest change", cli.HELP_TEXT)

    def test_recent_sessions_are_newest_first(self):
        with tempfile.TemporaryDirectory() as root:
            store = SessionStore(Path(root) / "sessions")
            for index in range(6):
                store.save({"id": str(index), "memory": {"task": f"task {index}"}})
                os.utime(store.path(str(index)), (index + 1, index + 1))
            self.assertEqual([item["id"] for item in store.recent(5)], ["5", "4", "3", "2", "1"])

    def test_bare_resume_lists_sessions_and_uses_selection(self):
        with tempfile.TemporaryDirectory() as root:
            store = SessionStore(Path(root) / ".mini-coding-agent" / "sessions")
            store.save({"id": "session-a", "memory": {"task": "inspect cache\nthen fix it"}})
            output = io.StringIO()
            selected = {}

            def from_session(client, workspace, session_store, session_id, **kwargs):
                selected["id"] = session_id
                instance = unittest.mock.Mock()
                instance.session = {"id": session_id}
                return instance

            with redirect_stdout(output), patch("builtins.input", side_effect=["1", "/exit"]), patch.object(cli, "build_model_client", return_value=object()), patch.object(cli.MyAgent, "from_session", side_effect=from_session):
                cli.run(["--cwd", root, "--resume"])
            self.assertEqual(selected["id"], "session-a")
            self.assertIn("session-a  inspect cache then fix it", output.getvalue())

    def test_explicit_latest_resume_remains_supported(self):
        with tempfile.TemporaryDirectory() as root:
            store = SessionStore(Path(root) / ".mini-coding-agent" / "sessions")
            store.save({"id": "latest-id", "memory": {"task": "latest task"}})
            selected = {}

            def from_session(client, workspace, session_store, session_id, **kwargs):
                selected["id"] = session_id
                instance = unittest.mock.Mock()
                instance.session = {"id": session_id}
                return instance

            with patch("builtins.input", return_value="/exit"), patch.object(cli, "build_model_client", return_value=object()), patch.object(cli.MyAgent, "from_session", side_effect=from_session):
                cli.run(["--cwd", root, "--resume", "latest"])
            self.assertEqual(selected["id"], "latest-id")


if __name__ == "__main__":
    unittest.main()
