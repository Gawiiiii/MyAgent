import json
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from audit import AuditLog
from model_client import FakeModelClient
from my_agent import MyAgent


class Stage8Tests(unittest.TestCase):
    def test_audit_log_writes_jsonl_and_reads_limit(self):
        with TemporaryDirectory() as directory:
            log = AuditLog(Path(directory) / "audit" / "session.jsonl")
            log.append("first", value="x")
            log.append("second", value="y")
            self.assertEqual([item["event"] for item in log.read(1)], ["second"])
            lines = Path(directory, "audit", "session.jsonl").read_text(encoding="utf-8").splitlines()
            record = json.loads(lines[0])
            self.assertEqual(record["session_id"], "session")
            self.assertIn("timestamp", record)

    def test_agent_records_event_order_and_clips_sensitive_fields(self):
        with TemporaryDirectory() as directory:
            client = FakeModelClient(['<tool>{"name":"list_files","args":{}}</tool>', "<final>done</final>"])
            agent = MyAgent(client, directory)
            self.assertEqual(agent.ask("inspect"), "done")
            agent.audit_log.append("credentials", api_key="do-not-write", output="x" * 5000)
            events = agent.audit_log.read()
            names = [item["event"] for item in events]
            self.assertLess(names.index("model_request"), names.index("model_response"))
            self.assertLess(names.index("tool_start"), names.index("tool_result"))
            self.assertLess(names.index("tool_result"), names.index("final_answer"))
            credential = events[-1]
            self.assertEqual(credential["api_key"], "[redacted]")
            self.assertLessEqual(len(credential["output"]), 4040)

    def test_audit_clear_removes_only_audit_file(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(FakeModelClient(["<final>done</final>"]), directory)
            agent.ask("task")
            session_path = Path(directory, ".mini-coding-agent", "sessions", f"{agent.session['id']}.json")
            self.assertTrue(session_path.exists())
            agent.audit_log.clear()
            self.assertFalse(agent.audit_log.path.exists())
            self.assertTrue(session_path.exists())

    def test_cli_audit_commands_display_and_clear(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(FakeModelClient([]), directory)
            agent.audit_log.append("manual")
            with patch("cli.build_model_client", return_value=FakeModelClient([])), patch("cli.MyAgent", return_value=agent), patch(
                "builtins.input", side_effect=["/audit 1", "/audit-clear", "/exit"]
            ), patch("sys.stdout", new_callable=StringIO) as output:
                from cli import main

                main(["--cwd", directory])
            self.assertIn("manual", output.getvalue())
            self.assertIn("audit cleared", output.getvalue())


if __name__ == "__main__":
    unittest.main()
