import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from audit import AuditLog
from model_client import FakeModelClient, OpenAICompatibleModelClient
from my_agent import MyAgent
from tools import list_files, search
from workspace import WorkspaceContext


class MetadataHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        payload = json.dumps({
            "choices": [{
                "message": {"content": "", "reasoning_content": "reasoning trace"},
                "finish_reason": "length",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


class ReliabilityTests(unittest.TestCase):
    def test_same_tool_is_allowed_in_separate_asks(self):
        with TemporaryDirectory() as directory:
            call = '<tool>{"name":"list_files","args":{}}</tool>'
            agent = MyAgent(FakeModelClient([call, "<final>one</final>", call, "<final>two</final>"]), directory)
            self.assertEqual(agent.ask("first"), "one")
            self.assertEqual(agent.ask("second"), "two")
            results = [item["content"] for item in agent.session["history"] if item["role"] == "tool"]
            self.assertFalse(any("repeated tool call" in item for item in results))

    def test_three_empty_responses_stop_early(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(FakeModelClient(["", "", "", "<final>unused</final>"]), directory)
            answer = agent.ask("task")
            self.assertIn("3 consecutive empty", answer)
            requests = [item for item in agent.audit_log.read() if item["event"] == "model_request"]
            self.assertEqual(len(requests), 3)

    def test_final_is_allowed_after_last_tool_step(self):
        with TemporaryDirectory() as directory:
            call = '<tool>{"name":"list_files","args":{}}</tool>'
            agent = MyAgent(FakeModelClient([call, "<final>done</final>"]), directory, max_steps=1)
            self.assertEqual(agent.ask("task"), "done")

    def test_openai_metadata_is_extracted_and_audited(self):
        server = HTTPServer(("127.0.0.1", 0), MetadataHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with TemporaryDirectory() as directory:
                client = OpenAICompatibleModelClient("demo", f"http://127.0.0.1:{server.server_port}", "key")
                agent = MyAgent(client, directory)
                agent.ask("task")
                response = next(item for item in agent.audit_log.read() if item["event"] == "model_response")
                self.assertEqual(response["finish_reason"], "length")
                self.assertEqual(response["usage"]["completion_tokens"], 20)
                self.assertEqual(response["reasoning_content"], "reasoning trace")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_internal_directory_is_hidden(self):
        with TemporaryDirectory() as directory:
            internal = Path(directory, ".mini-coding-agent")
            internal.mkdir()
            Path(internal, "secret.json").write_text("needle", encoding="utf-8")
            Path(directory, "visible.txt").write_text("needle", encoding="utf-8")
            self.assertEqual(list_files(directory, {}), "visible.txt")
            self.assertNotIn("secret.json", search(directory, {"pattern": "needle"}))
            workspace = WorkspaceContext.build(directory)
            self.assertNotIn(".mini-coding-agent", workspace.status)

    def test_max_new_tokens_is_not_redacted(self):
        with TemporaryDirectory() as directory:
            log = AuditLog(Path(directory, "session.jsonl"))
            log.append("request", max_new_tokens=4096, api_key="secret")
            record = log.read()[0]
            self.assertEqual(record["max_new_tokens"], 4096)
            self.assertEqual(record["api_key"], "[redacted]")


if __name__ == "__main__":
    unittest.main()
