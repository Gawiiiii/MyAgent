"""真实模型集成测试；需显式设置 MYAGENT_RUN_FULL_TESTS=1 才运行。"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HAS_CONFIGURATION = bool(os.environ.get("DEEPSEEK_API_KEY")) or (PROJECT_ROOT / ".env").exists()
RUN_REAL_API = os.environ.get("MYAGENT_RUN_FULL_TESTS") == "1" and HAS_CONFIGURATION


@unittest.skipUnless(RUN_REAL_API, "set MYAGENT_RUN_FULL_TESTS=1 and configure .env/API key")
class RealAPITests(unittest.TestCase):
    """通过真实模型进程验证当前 Agent 的集成行为。"""

    def run_agent(self, request, cwd, approval="never", max_steps=8):
        """运行真实 CLI 请求；参数为 str 请求、Path 工作区、审批模式和步数，返回 CompletedProcess。"""
        environment = os.environ.copy()
        command = [
            sys.executable, str(PROJECT_ROOT / "my_agent.py"), "--cwd", str(cwd),
            "--approval", approval, "--max-steps", str(max_steps), request,
        ]
        return subprocess.run(command, cwd=PROJECT_ROOT, env=environment, text=True, capture_output=True, timeout=180)

    def assert_stable_response(self, result):
        """断言 CLI 没有 Python 崩溃；参数为 CompletedProcess，返回 None。"""
        self.assertNotIn("Traceback (most recent call last)", result.stderr)
        self.assertNotIn("Connection refused", result.stderr)
        self.assertTrue(result.stdout or result.stderr)

    def test_real_read_loop(self):
        """验证真实模型能够列目录并读取 README；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            Path(directory, "README.md").write_text("full test README\n", encoding="utf-8")
            result = self.run_agent("列出当前目录并读取 README.md", directory)
            self.assert_stable_response(result)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("<final>", result.stdout)

    def test_real_coding_tools_loop(self):
        """验证真实模型尝试搜索、创建、修改并运行测试；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            request = "创建 binary_search.py 和 test_binary_search.py，运行 pytest；如失败请修复并给出总结。"
            result = self.run_agent(request, directory, approval="auto", max_steps=12)
            self.assert_stable_response(result)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_never_approval_does_not_write(self):
        """验证真实模型在 never 模式下不能执行写入；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            result = self.run_agent("请创建 forbidden.txt，内容为 blocked", directory, approval="never")
            self.assert_stable_response(result)
            self.assertFalse(Path(directory, "forbidden.txt").exists())

    def test_real_edge_inputs_return_text_errors(self):
        """验证越界路径、空搜索和超时请求不会让进程静默退出；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            request = "搜索空模式，读取 ../outside.txt，并运行 timeout=121 的命令；报告每个错误。"
            result = self.run_agent(request, directory, approval="never", max_steps=10)
            self.assert_stable_response(result)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("<final>", result.stdout)


if __name__ == "__main__":
    unittest.main()
