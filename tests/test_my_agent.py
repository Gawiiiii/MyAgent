import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from model_client import OpenAICompatibleModelClient, OllamaModelClient, load_env_file
from my_agent import MyAgent
from parser import parse


class RecordingHandler(BaseHTTPRequestHandler):
    responses = []
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.__class__.requests.append((self.path, dict(self.headers), json.loads(body)))
        response = self.__class__.responses.pop(0)
        payload = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


class LocalModelServer:
    def __enter__(self):
        RecordingHandler.responses = []
        RecordingHandler.requests = []
        self.server = HTTPServer(("127.0.0.1", 0), RecordingHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}"

    def __exit__(self, *_args):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()


class CurrentVersionTests(unittest.TestCase):
    def test_openai_client_sends_required_payload_and_auth(self):
        with LocalModelServer() as base_url:
            RecordingHandler.responses = [{"choices": [{"message": {"content": "<final>ok</final>"}}]}]
            client = OpenAICompatibleModelClient("demo", base_url, "test-secret")
            self.assertEqual(client.complete("hello", 64), "<final>ok</final>")
            path, headers, payload = RecordingHandler.requests[0]
            self.assertEqual(path, "/v1/chat/completions")
            self.assertEqual(headers["Authorization"], "Bearer test-secret")
            self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])
            self.assertEqual(payload["max_tokens"], 64)

    def test_ollama_client_uses_native_generate_endpoint(self):
        with LocalModelServer() as host:
            RecordingHandler.responses = [{"response": "<final>ollama</final>"}]
            client = OllamaModelClient("demo", host)
            self.assertEqual(client.complete("hello", 32), "<final>ollama</final>")
            path, _headers, payload = RecordingHandler.requests[0]
            self.assertEqual(path, "/api/generate")
            self.assertFalse(payload["stream"])
            self.assertEqual(payload["options"]["num_predict"], 32)

    def test_real_client_and_agent_complete_tool_loop(self):
        with TemporaryDirectory() as directory, LocalModelServer() as base_url:
            Path(directory, "README.md").write_text("first line\n", encoding="utf-8")
            RecordingHandler.responses = [
                {"choices": [{"message": {"content": '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>'}}]},
                {"choices": [{"message": {"content": "<final>读取完成</final>"}}]},
            ]
            client = OpenAICompatibleModelClient("demo", base_url, "test-secret")
            self.assertEqual(MyAgent(client, directory).ask("读取 README.md"), "读取完成")
            self.assertEqual(len(RecordingHandler.requests), 2)
            self.assertIn("1: first line", RecordingHandler.requests[1][2]["messages"][0]["content"])

    def test_env_file_is_loaded_for_real_client_configuration(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory, ".env")
            env_path.write_text("DEEPSEEK_API_KEY=file-secret\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                load_env_file(str(env_path))
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "file-secret")

    def test_read_only_tool_table_exposes_second_stage_gaps(self):
        with TemporaryDirectory() as directory:
            class WriteRequestClient:
                def complete(self, _prompt, _max_new_tokens):
                    return '<tool>{"name":"write_file","args":{"path":"new.txt","content":"x"}}</tool>'

            agent = MyAgent(WriteRequestClient(), directory, max_steps=1)
            self.assertEqual(set(agent.tools), {"list_files", "read_file"})
            self.assertEqual(parse('<tool>{"name":"write_file","args":{}}</tool>')["kind"], "tool")
            with self.assertRaises(RuntimeError):
                agent.ask("创建一个文件")


if __name__ == "__main__":
    unittest.main()
