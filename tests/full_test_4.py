"""阶段七真实 API 预览和回滚测试；需显式设置 MYAGENT_RUN_FULL_TESTS=1。"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from model_client import OpenAICompatibleModelClient, load_env_file
from my_agent import MyAgent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HAS_CONFIGURATION = bool(os.environ.get("DEEPSEEK_API_KEY")) or (PROJECT_ROOT / ".env").exists()
RUN_REAL_API = os.environ.get("MYAGENT_RUN_FULL_TESTS") == "1" and HAS_CONFIGURATION


@unittest.skipUnless(RUN_REAL_API, "set MYAGENT_RUN_FULL_TESTS=1 and configure .env/API key")
class RealChangeWorkflowTests(unittest.TestCase):
    def setUp(self):
        load_env_file(str(PROJECT_ROOT / ".env"))
        self.client = OpenAICompatibleModelClient(
            "deepseek-v4-flash", "https://api.deepseek.com", os.environ["DEEPSEEK_API_KEY"]
        )

    def test_real_agent_can_create_test_and_report(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(self.client, directory, approval="auto", max_steps=10)
            answer = agent.ask("创建 hello.py，写一个返回 hello 的函数，并创建测试后运行 pytest，最后总结。")
            self.assertTrue(answer.strip())
            self.assertNotIn("Traceback", answer)
            self.assertTrue(Path(directory, "hello.py").exists())
            self.assertTrue(agent.changes)

    def test_real_agent_session_can_rollback_last_change(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(self.client, directory, approval="auto", max_steps=8)
            answer = agent.ask("创建 rollback_target.txt，内容为 temporary，然后给出简短总结。")
            self.assertTrue(answer.strip())
            self.assertTrue(Path(directory, "rollback_target.txt").exists())
            result = agent.rollback()
            self.assertNotIn("error:", result)
            self.assertFalse(Path(directory, "rollback_target.txt").exists())


if __name__ == "__main__":
    unittest.main()
