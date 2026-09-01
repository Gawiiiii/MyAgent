import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cli import main
from model_client import FakeModelClient
from my_agent import MyAgent


class Stage5Tests(unittest.TestCase):
    def test_fake_client_returns_outputs_in_order(self):
        client = FakeModelClient(["one", "two"])
        self.assertEqual(client.complete("", 1), "one")
        self.assertEqual(client.complete("", 1), "two")

    def test_delegate_is_read_only_and_returns_result(self):
        with TemporaryDirectory() as directory:
            Path(directory, "README.md").write_text("hello", encoding="utf-8")
            client = FakeModelClient([
                '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
                "<final>analysis complete</final>",
            ])
            agent = MyAgent(client, directory, approval="auto")
            result = agent.run_tool("delegate", {"task": "read README"})
            self.assertIn("delegate_result: analysis complete", result)
            self.assertFalse(Path(directory, "created.txt").exists())

    def test_delegation_depth_is_bounded(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(FakeModelClient([]), directory, max_depth=0)
            self.assertIn("maximum delegation depth", agent.run_tool("delegate", {"task": "inspect"}))

    def test_malformed_tool_retries(self):
        with TemporaryDirectory() as directory:
            client = FakeModelClient(["<tool>{bad json}</tool>", "<final>recovered</final>"])
            self.assertEqual(MyAgent(client, directory).ask("task"), "recovered")

    def test_patch_requires_unique_match_and_parent_escape_is_denied(self):
        with TemporaryDirectory() as directory:
            Path(directory, "same.txt").write_text("x x", encoding="utf-8")
            agent = MyAgent(FakeModelClient([]), directory, approval="auto")
            duplicate = agent.run_tool("patch_file", {"path": "same.txt", "old_text": "x", "new_text": "y"})
            self.assertIn("exactly once", duplicate)
            self.assertIn("path escapes workspace", agent.run_tool("read_file", {"path": "../outside.txt"}))

    def test_read_only_agent_exposes_only_safe_tools(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(FakeModelClient([]), directory, read_only=True)
            self.assertEqual(set(agent.tools), {"list_files", "read_file", "search"})

    def test_cli_prints_welcome_in_interactive_mode(self):
        with TemporaryDirectory() as directory:
            with patch("cli.build_model_client", return_value=FakeModelClient([])), patch(
                "builtins.input", side_effect=EOFError
            ), patch("sys.stdout", new_callable=StringIO) as output:
                main(["--cwd", directory])
            self.assertIn("MyAgent interactive mode", output.getvalue())


if __name__ == "__main__":
    unittest.main()
