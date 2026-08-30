import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from model_client import OpenAICompatibleModelClient, load_env_file

from my_agent import MyAgent
from parser import parse
from tools import list_files, read_file


class FakeModelClient:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.prompts = []

    def complete(self, prompt, max_new_tokens):
        self.prompts.append(prompt)
        return next(self.outputs)


class MyAgentTests(unittest.TestCase):
    def test_tool_then_final(self):
        with TemporaryDirectory() as directory:
            from pathlib import Path
            root = Path(directory)
            (root / "README.md").write_text("hello\nworld\n", encoding="utf-8")
            client = FakeModelClient(['<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>', '<final>已读取。</final>'])
            self.assertEqual(MyAgent(client, root).ask("读取 README"), "已读取。")
            self.assertIn("1: hello", client.prompts[1])

    def test_retry_malformed_then_final(self):
        with TemporaryDirectory() as directory:
            client = FakeModelClient(["", "<final>ok</final>"])
            self.assertEqual(MyAgent(client, directory).ask("test"), "ok")
            self.assertIn("format error", client.prompts[1])

    def test_tools_are_minimal_and_safe(self):
        with TemporaryDirectory() as directory:
            from pathlib import Path
            root = Path(directory)
            (root / "b.txt").write_text("b\n", encoding="utf-8")
            (root / "a").mkdir()
            self.assertEqual(list_files(root, {}), "a/\nb.txt")
            self.assertEqual(read_file(root, {"path": "b.txt", "start": 1, "end": 1}), "1: b")
            with self.assertRaisesRegex(ValueError, "escapes workspace"):
                read_file(root, {"path": "../secret"})

    def test_parser_protocol_and_invalid_tool(self):
        self.assertEqual(parse('<final>x</final>'), {"kind": "final", "content": "x"})
        self.assertEqual(parse('<tool>{"name":"list_files","args":{}}</tool>')["kind"], "tool")
        self.assertEqual(parse('<tool>{"name":"read_file","args":[]}</tool>')["kind"], "retry")

    def test_openai_base_url_does_not_duplicate_v1(self):
        client = OpenAICompatibleModelClient("demo", "http://model/v1", "secret")
        with patch("model_client.urllib.request.urlopen") as open_url:
            response = open_url.return_value.__enter__.return_value
            response.read.return_value = b'{"choices":[{"message":{"content":"ok"}}]}'
            self.assertEqual(client.complete("hello", 10), "ok")
            self.assertEqual(open_url.call_args.args[0].full_url, "http://model/v1/chat/completions")

    def test_env_file_loads_key_without_overriding_environment(self):
        with TemporaryDirectory() as directory:
            from pathlib import Path
            env_path = Path(directory) / ".env"
            env_path.write_text("DEMO_KEY=file-value\n# ignored\n", encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True):
                load_env_file(str(env_path))
                self.assertEqual(os.environ["DEMO_KEY"], "file-value")
            with patch.dict("os.environ", {"DEMO_KEY": "existing"}, clear=True):
                load_env_file(str(env_path))
                self.assertEqual(os.environ["DEMO_KEY"], "existing")


if __name__ == "__main__":
    unittest.main()
