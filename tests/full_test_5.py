"""阶段八真实 API 审计测试；需显式设置 MYAGENT_RUN_FULL_TESTS=1。"""

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
class RealAuditTests(unittest.TestCase):
    def setUp(self):
        load_env_file(str(PROJECT_ROOT / ".env"))
        self.client = OpenAICompatibleModelClient(
            "deepseek-v4-flash", "https://api.deepseek.com", os.environ["DEEPSEEK_API_KEY"]
        )

    def test_real_read_delegate_write_and_shell_are_audited(self):
        with TemporaryDirectory() as directory:
            agent = MyAgent(self.client, directory, approval="auto", max_steps=12)
            answer = agent.ask("读取当前目录，分析 README；创建 audit_target.py 并运行一个简单的 pytest，最后总结。")
            self.assertTrue(answer.strip())
            self.assertTrue(agent.audit_log.path.exists())
            events = agent.audit_log.read()
            event_names = {item["event"] for item in events}
            self.assertIn("model_request", event_names)
            self.assertIn("model_response", event_names)
            self.assertIn("parse_result", event_names)
            self.assertIn("final_answer", event_names)
            self.assertNotIn("DEEPSEEK_API_KEY", agent.audit_log.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
