"""阶段六真实 API 并行只读委派测试；需显式设置 MYAGENT_RUN_FULL_TESTS=1。"""

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from model_client import OpenAICompatibleModelClient, load_env_file
from my_agent import MyAgent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HAS_CONFIGURATION = bool(os.environ.get("DEEPSEEK_API_KEY")) or (PROJECT_ROOT / ".env").exists()
RUN_REAL_API = os.environ.get("MYAGENT_RUN_FULL_TESTS") == "1" and HAS_CONFIGURATION


@unittest.skipUnless(RUN_REAL_API, "set MYAGENT_RUN_FULL_TESTS=1 and configure .env/API key")
class RealParallelDelegationTests(unittest.TestCase):
    def setUp(self):
        load_env_file(str(PROJECT_ROOT / ".env"))
        self.client = OpenAICompatibleModelClient(
            "deepseek-v4-flash", "https://api.deepseek.com", os.environ["DEEPSEEK_API_KEY"]
        )

    def test_three_read_only_tasks_preserve_workspace_and_return_results(self):
        with TemporaryDirectory() as directory:
            Path(directory, "README.md").write_text("parallel test", encoding="utf-8")
            before = sorted(path.relative_to(directory).as_posix() for path in Path(directory).rglob("*"))
            agent = MyAgent(self.client, directory, max_steps=6, max_depth=1, max_parallel_delegates=3)
            started = time.monotonic()
            result = agent.run_tool("delegate_parallel", {"tasks": [
                "只读分析 README.md 的内容并给出一句话摘要。",
                "只读列出当前工作区文件，不要修改文件。",
                "只读搜索 README.md 中的 parallel，并说明是否命中。",
            ]})
            elapsed = time.monotonic() - started
            after = sorted(path.relative_to(directory).as_posix() for path in Path(directory).rglob("*"))
            self.assertEqual(before, after)
            self.assertEqual(result.count("delegate_result["), 3)
            self.assertNotIn("Traceback", result)
            self.assertGreater(elapsed, 0)

    def test_max_parallel_one_remains_compatible(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(self.client, directory, max_steps=4, max_parallel_delegates=1)
            result = agent.run_tool("delegate_parallel", {"tasks": ["只读列出当前目录。"]})
            self.assertIn("delegate_result[1]:", result)


if __name__ == "__main__":
    unittest.main()
