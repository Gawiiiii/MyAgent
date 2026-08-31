"""第二轮真实 API 集成测试；需设置 MYAGENT_RUN_FULL_TESTS=1 才运行。"""

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
class MultiStageRealAPITests(unittest.TestCase):
    """验证真实模型在多个 CLI 进程和用户阶段中的持续编程能力。"""

    def run_agent(self, request, cwd, resume="", max_steps=12):
        """执行一次真实 CLI 请求；参数为任务文本、工作区、可选会话和步数，返回 CompletedProcess。"""
        command = [sys.executable, str(PROJECT_ROOT / "my_agent.py"), "--cwd", str(cwd), "--approval", "auto", "--max-steps", str(max_steps)]
        if resume:
            command.extend(["--resume", resume])
        command.append(request)
        return subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=240)

    def assert_no_crash(self, result):
        """检查真实调用没有 Python Traceback；参数为 CompletedProcess，返回 None。"""
        self.assertNotIn("Traceback (most recent call last)", result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<final>", result.stdout)

    def test_multi_stage_create_test_fix_and_report(self):
        """分三阶段创建、测试、修复二分查找并报告；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            first = self.run_agent("创建 binary_search.py，实现升序整数列表的二分查找函数，并说明接口。", directory)
            self.assert_no_crash(first)
            self.assertTrue(Path(directory, "binary_search.py").exists())

            second = self.run_agent("为 binary_search.py 创建 pytest 测试，覆盖命中、未命中和空列表，并运行 pytest。", directory, resume="latest")
            self.assert_no_crash(second)
            self.assertTrue(any(path.name.startswith("test_") for path in Path(directory).iterdir()))

            third = self.run_agent("检查刚才的实现和测试结果；如果测试失败请精确修改代码并重新运行 pytest，最后总结变更。", directory, resume="latest")
            self.assert_no_crash(third)

    def test_multi_stage_context_survives_resume(self):
        """验证新进程通过 latest 会话看到前一阶段文件和任务；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            first = self.run_agent("创建 notes.txt，写入阶段一完成，然后列出当前目录。", directory)
            self.assert_no_crash(first)
            second = self.run_agent("读取刚才创建的 notes.txt，追加一行阶段二完成，并确认原内容仍在。", directory, resume="latest")
            self.assert_no_crash(second)
            content = Path(directory, "notes.txt").read_text(encoding="utf-8")
            self.assertIn("阶段一", content)
            self.assertIn("阶段二", content)

    def test_multi_stage_failure_recovery_and_safe_boundary(self):
        """验证先制造失败再修复，并在 never 模式下阻止危险操作；无参数，返回 None。"""
        with TemporaryDirectory() as directory:
            first = self.run_agent("创建 broken.py 和 test_broken.py，让测试先故意失败，然后运行 pytest 并报告失败。", directory)
            self.assert_no_crash(first)
            second = self.run_agent("分析 pytest 失败原因，使用 patch_file 修复 broken.py，重新运行测试直到通过。", directory, resume="latest")
            self.assert_no_crash(second)
            forbidden = subprocess.run([
                sys.executable, str(PROJECT_ROOT / "my_agent.py"), "--cwd", directory,
                "--approval", "never", "请创建 should_not_exist.txt，内容为 blocked。",
            ], cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=180)
            self.assert_no_crash(forbidden)
            self.assertFalse(Path(directory, "should_not_exist.txt").exists())


if __name__ == "__main__":
    unittest.main()
